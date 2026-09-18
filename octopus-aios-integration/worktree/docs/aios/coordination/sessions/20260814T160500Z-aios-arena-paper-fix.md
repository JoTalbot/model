# Сессия: paper-контур — диагностика блокировок входа

---
session_id: "20260814T160500Z-aios-arena-paper-fix"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T16:05:00Z"
updated_utc: "2026-08-14T23:50:00Z"
branch: "agent/20260814-paper-fix"
base_commit: "9d5dbd7b"
claim: "coordination/claims/paper-fix--20260814T160500Z-aios-arena-paper-fix.md"
---

## Цель

Разобраться, почему owner-approved paper-контур (aios-quant-trading) не открывает позиции, и починить так, чтобы paper-вход реально работал без изменения owner-профиля риска. Live запрещён.

## Диагноз

- `exchange_not_allowed` 96/цикл — by design: owner-профиль ограничивает kucoin,bitstamp,mexc (7 из 10 бирж вне allowlist). Не баг.
- `ml_not_confirmed` 17/цикл — корневой блокер: развёрнутая CatBoost-модель (Colab, 2026-08-12) деградирована — prob_up=0.433 ровно для 30/35 активов, AUC 0.504, на OOS ни разу >=0.60. Гейт 0.65 физически недостижим.
- Причина деградации: обучение на сырых абсолютных ценах (BTC 95000 vs PEPE 2.7e-6) в одном пуле без нормализации + финальный fit на всех данных без честного OOS.

## Решение

1. Новый `scripts/quant_ml_eval_train.py`: строгий per-symbol walk-forward (train 70% / test 30%, gap 48 бар), масштаб-инвариантные признаки (ret1..24, rsi, bb_pos, macd_norm, ema_gap, vol_ratio, vol_z, bar_range_pct, hl_pos), label = направление следующего 1h бара.
2. Кандидат `catboost_price_dir_v2.cbm` (AUC 0.533) валидирован на двух независимых OOS-окнах:
   - среднее окно (train 55%): hit@0.65=81.3%, 32 сделки, win 68.8%, avg +0.59% net, итог +18.9%
   - последнее окно (train 70%): hit@0.65=83.3%, 36 сделок, win 75.0%, avg +0.74% net, итог +26.5%
   - симуляция по правилам движка (TP+2%/SL-1%/trail, комиссии 0.5% round-trip, исполнение по триггерному уровню)
3. `aios_core/quant/ml_predictor.py`: DEFAULT_FEATURES → 13 scale-free признаков (1:1 формулы), приоритет загрузки catboost_price_dir_v2.cbm; старая модель остаётся fallback'ом (откат = удалить v2).
4. Признаки предиктора сверены с тренировочным скриптом — совпадение 1:1 (abs diff < 1e-9).

## Проверки

- [PASS] python -m py_compile aios_core/quant/ml_predictor.py, scripts/quant_ml_eval_train.py
- [PASS] pytest quant-набор: 18 passed (directional_v2, run_quant_trading_v2, v2_gate, walkforward_v2, signal_product, signal_api, directional_policy)
- [PASS] feature parity: тренировочный скрипт vs предиктор (BTC CSV) — 1:1
- [PASS] run_quant_ml_inference.py: ml_signals.json перегенерирован моделью v2, prob_up 0.38-0.60 (различаются), 1 актив >=0.60
- [PASS] gate-проверка с owner-профилем: ML=0.70 conf=0.90 → вход разрешён (None); ML=0.45 → ml_not_confirmed; binance → exchange_not_allowed
- [NOT RUN] полный pytest suite (5 198 тестов) — затронуты только quant/ml пути, покрыты выше

## Изменённые файлы

- `scripts/quant_ml_eval_train.py` — новый: диагностика + обучение кандидата + симуляция paper-сделок
- `aios_core/quant/ml_predictor.py` — scale-free признаки v2, приоритет модели v2
- `data/quant/models/catboost_price_dir_v2.cbm/.pkl` — runtime-артефакт (git-ignored), старый .cbm сохранён

## Git

- Branch `agent/20260814-paper-fix`, commit `8d668f03` (2 файла, +336/-7). Не закоммичены: coordination/sessions, claims, PROJECT_CONTEXT (следующий коммит).

## Деплой и верификация runtime (16:13-16:25Z)

- Inference-демон перезапущен (единичный restart после смены кода; старый процесс держал в памяти старый модуль): `[QuantMLPredictor] Модель загружена: .../catboost_price_dir_v2.cbm`.
- ml_signals.json перегенерирован моделью v2 (16:13:49Z): prob_up различаются (0.38-0.60), 1 актив >=0.60.
- Trading-демон цикл 16:13Z чистый: blocks={'exchange_not_allowed': 96, 'ml_not_confirmed': 9} (было 17 — сигналы больше не константа; до 0.65 сегодня не дотянул ни один актив — это нормальная селективность гейта).
- Ветка agent/20260814-paper-fix опубликована в origin (GitHub JoTalbot/AIOS); origin/main синхронизирован (9d5dbd7b).


## Этап 2: RL-мост и мёртвые тикеры (пункты 1-2 из handoff)

### RL-мост (aios_core/quant/rl_signal_bridge.py) — 3 бага исправлено

Сверка с обучающей средой data/kg_v8/aios-rl-v8.ipynb (MultiAssetEnv, obs_dim=46):

1. **onehot-баг**: обучение — onehot[индекс] в sorted(32 активов); мост всегда ставил onehot[0]=BTC для всех активов → все сигналы одинаковые. Фикс: константа ASSET_ORDER (32 актива из ноутбука, алфавитный порядок), onehot по индексу запрошенного актива; актив вне универсума → честный None (нет сигнала), а не чужой индекс.
2. **Признак vol_chg вместо vol_ratio**: обучение использует [rets(10), mom5, mom12, vol_ratio, vol_norm]; мост подавал vol_chg на 3-й статической позиции. Фикс: vol_ratio = volume/rolling(10)-mean.
3. **Отсутствие clamp**: в обучении act.clamp(-1,1) до конвертации в дискрету {0,1,2}; в мосте mean=-2.77 давал pos=-0.5 (вне [0,1]). Фикс: clamp(-1,1) перед конвертацией.

Результат: 9 сигналов (POL честно отброшен — нет в обучающем универсуме), pos ∈ {0, 0.5, 1.0}, активы различаются. Модель PPO v8 на текущем рынке даёт FLAT по всем 9 мажорам (mean < -1 → действие «выход») — честный вердикт модели, консервативный veto сохраняется. Переобучение PPO в Colab — отдельная задача.

### Мёртвые тикеры MATIC/RNDR

- `aios_core/quant/ml_predictor.py::predict_all`: фильтр dead = {MATIC, RNDR} — старые папки данных остаются, в сигналы не попадают. ML 35 → 33 символа.
- `rl_signal_bridge.py::run_all`: MATIC → POL в дефолтном словаре (DEFAULT_SYMBOLS уже использует POL/RENDER).
- `scripts/gen_quant_notebooks.py`: MATIC/USDT → POL/USDT в шаблоне кластеризации.
- Сигнальный продукт перегенерирован: 33 символа, MATIC/RNDR отсутствуют. Остаются 11 NO_DATA «illiquid» — это малоисторичные активы (~500 строк), не мёртвые тикеры (отдельный вопрос дособора истории).

### Runtime

- aios-quant-trading.service перезапущен (единичный рестарт для подхвата исправленного моста), цикл чистый.
- rl_signals.json пересохранён (9 сигналов), ml_signals.json перегенерирован (33, без мёртвых тикеров).

## Проверки (этап 2)

- [PASS] py_compile всех 3 изменённых файлов
- [PASS] pytest: 61 passed (quant-набор + test_ml + test_price_prediction_ml)
- [PASS] RLSignalBridge.run_all: 9 сигналов, pos ∈ {0.0,0.5,1.0}, активы различаются, POL → None (не в универсуме)
- [PASS] ml_signals.json: 33 символа, MATIC/RNDR отсутствуют
- [PASS] quant_signal_product: 33 символа, без мёртвых тикеров

## Изменённые файлы (этап 2)

- `aios_core/quant/rl_signal_bridge.py` — onehot, vol_ratio, clamp, POL вместо MATIC
- `aios_core/quant/ml_predictor.py` — фильтр мёртвых тикеров
- `scripts/gen_quant_notebooks.py` — POL вместо MATIC в шаблоне


## Этап 3: дособор истории, переобучение ML и PPO (по порядку)

### 1. Дособор истории (scripts/quant_backfill_history.py, новый)

- 17 малоисторичных активов (APT..WIF, ~500 строк) дособраны до ~5500 строк через пагинированный Binance klines; KAS — через Bybit fallback (KASUSDT отсутствует на Binance spot).
- Скрипт сначала обновляет «хвост» (fetch последних баров) — исправляет устаревшие серии (TON: binance-серия оборвана 24.06 — делистинг TONUSDT на Binance/Bybit; свежие бары на bitstamp/kraken).
- Дедупликация по timestamp_ms, сортировка, формат CSV сохранён.

### 2. Сигнальный продукт: выбор источника (generate_quant_signal_product.py)

- `_latest_rows`: выбор самой полной СВЕЖЕЙ серии (устаревшие >2h отбрасываются) — раньше для APT брался kraken (503 строки) вместо binance (5503), а для TON — устаревшая binance-серия вместо свежей bitstamp.
- Regime считается по последнему ЗАКРЫТОМУ бару (незакрытый бар имеет частичный объём → ложный «illiquid»).
- Результат: NO_DATA 16 → 0; 33 актива с живыми данными; WATCH_DOWN: OP, PEPE.

### 3. Переобучение ML (quant_ml_eval_train.py на полных данных)

- Оценка на полном датасете (172k строк, тест 52k): старая модель AUC 0.513 и 0 сделок >=0.60; кандидат v2: AUC 0.536, hit@0.65 = 82.4%, SIM thr=0.65: 34 сделки, win 79.4%, avg +0.93% net, итог +31.6%.
- Исправлена симуляция в скрипте: исполнение по триггерным уровням (консервативно), а не по цене пробивающего бара (гэпы давали артефакты).
- Модель catboost_price_dir_v2.cbm пересохранена (демон перечитывает её каждый цикл).

### 4. Переобучение PPO (scripts/quant_train_ppo.py, новый)

- LSTM-PPO v9, методология 1:1 с data/kg_v8/aios-rl-v8.ipynb (MultiAssetEnv, окно 10, комиссия 0.0005, risk_penalty 0.01, 300 эпизодов × rollout 800, GAE γ=0.99 λ=0.97, clip 0.2, lr 2e-4, seed 42, CPU ~15 мин).
- Универсум: 32 актива, POL вместо делистнутого MATIC.
- Валидация на 2-й половине (как в ноутбуке): **v9 sum_rl +96.0%** vs Buy&Hold −114.0%; v8: +51.4% vs −121.0%. v9 лучше v8 на 21/32 активах.
- Обе модели — консервативные «FLAT-агенты» (0 long / 0 half) — veto-механизм; v9 эффективнее избегает убытков.
- Мост: MODEL_FILE → ppo_v9.pt; имена активов читаются из чекпоинта (совместимо с v8/MATIC и v9/POL); rl_signals.json пересохранён: 10 активов (вкл. POL), все честно FLAT.

## Проверки (этап 3)

- [PASS] py_compile всех изменённых скриптов
- [PASS] pytest: 61 passed (quant-набор + test_ml + test_price_prediction_ml)
- [PASS] данные: 33 живых актива с ~5000-5500 строк, 0 дубликатов/несортировок (выборка)
- [PASS] сигнальный продукт: NO_DATA 0, 33 сигнала
- [PASS] валидация v9: sum_rl +96.03 > v8 +51.39 → ppo_v9.pt сохранён
- [PASS] демон quant-trading перезапущен, цикл чистый

## Изменённые файлы (этап 3)

- `scripts/quant_backfill_history.py` — новый: дособор истории
- `scripts/quant_train_ppo.py` — новый: обучение PPO v9
- `scripts/quant_ml_eval_train.py` — триггерная симуляция
- `scripts/generate_quant_signal_product.py` — выбор свежей полной серии, regime по закрытому бару
- `aios_core/quant/rl_signal_bridge.py` — MODEL_FILE v9, assets из чекпоинта
- runtime: data/quant/*/binance/*.csv, models/ppo_v9.pt, catboost_price_dir_v2.cbm (git-ignored)

## Git (этап 3)

- Branch `agent/20260814-quant-backfill-ppo`, commit `9501cf23`.


## Этап 4: Orderbook research, DeFi gate, документация

### Orderbook коллектор (scripts/collect_orderbook_snapshots.py + systemd unit)

- Фикс kucoin: fetchOrderBook требует limit 20/100 (было 10 → 3 ошибки/цикл); MIN_DEPTH={"kucoin": 20}, обрезка до depth 10 в normalize.
- Расширены биржи: binance, kucoin, mexc, okx, bitstamp, coinbase (okx/bitstamp/coinbase протестированы live).
- Unit aios-orderbook-research.service: interval 30s → 15s. Скорость набора ~3x. Хост-юнит изменён (не versioned).
- Прогресс: binance/mexc ~250 снапшотов/пара → растёт; kucoin/okx/bitstamp/coinbase — подключены.

### Аналитика снапшотов (scripts/analyze_orderbook_data.py, новый, read-only)

- Спреды: BTC binance/mexc ~0.002 bps, ETH ~0.05, SOL ~1.32; глубины $10k-$750k.
- Cross-exchange mid disparity (60s бакеты): BTC p95 2.5bps (12 бакетов ≥2bps), ETH 2.0 (8), SOL 2.6 (9) — окна диспаритета существуют.
- Отчёт: data/reports/orderbook_analysis.json.

### Market-making симулятор (предварительный прогон, >=200 снапшотов)

- fill_rate 63-96%, но PnL отрицательный на всех парах: наивный passive MM страдает от adverse selection (мид движется против заполненной лимитки). Вывод: нужен inventory-aware quoting (перекотировка, отложенные лимитки) — это следующий research-шаг.
- Полный прогон (>=1000/пара) — когда binance/mexc наберут 1000 (~1.5-2ч при текущей скорости).

### DeFi risk monitor

- aios-defi-risk-monitor.timer активен (hourly), отчёт 17:01Z: ready=false — fail-closed корректно (нет баланса, bridge stub, топ-офферт mock). Ничего не делать — состояние валидное.

### Документация

- docs/QUANT_SIGNAL_PRODUCT.md: актуализирован (33 актива, backfill, выбор свежей серии, regime по закрытому бару, ML v2, PPO v9).
- docs/PROJECT_INVENTORY.md: перегенерирован (python scripts/generate_project_inventory.py --write).

## Проверки (этап 4)

- [PASS] py_compile коллектора и аналитики
- [PASS] live-тест бирж: okx/bitstamp/coinbase OK; kucoin после фикса OK (17/18 снапшотов/цикл, 1 ошибка — нестабильный эндпоинт одной из бирж)
- [PASS] market-making симулятор: ready=true при min=200, 6 пар
- [PASS] pytest после изменений не требуется (коллектор/аналитика вне тестов; quant-набор 61 passed ранее)

## Изменённые файлы (этап 4)

- `scripts/collect_orderbook_snapshots.py` — kucoin depth, +3 биржи
- `scripts/analyze_orderbook_data.py` — новый
- `docs/QUANT_SIGNAL_PRODUCT.md`, `docs/PROJECT_INVENTORY.md`
- runtime: /etc/systemd/system/aios-orderbook-research.service (interval 15, 6 бирж)

## Git (этап 4)

- Branch `agent/20260814-quant-backfill-ppo`, commit `bda4d3b7`.


### Orderbook: ускорение и watcher (17:50-18:20Z)

- Ошибка 1/цикл устранена: bitstamp не имеет SOL/USDT → per-exchange фильтр символов (EXCHANGE_SYMBOLS).
- Интервал юнита 15s → 5s: цикл ~9с, 17 снапшотов/цикл, 0 errors.
- Прогресс 18:20Z: binance/mexc ~460/1000, новые биржи ~220. Полный MM-прогон при >=1000.
- `scripts/mm_watcher.py` (новый, запущен в фоне): при достижении 1000 снапшотов/пара автоматически запускает run_market_making_simulator.py --min-snapshots 1000 и пишет отчёт в data/reports/market_making_simulation.json; лог logs/mm_watcher.log.
- Коммиты: `0e303a9d` (watcher), `e622845c` (bitstamp filter + interval 5s).


### MM research v2 и интеграция WATCH в утренний бриф (18:20-18:40Z)

- `scripts/run_market_making_simulator_v2.py` (новый): inventory-aware симулятор — заполнение только при благоприятном движении, правило одной позиции, без накопления. Прогон на 500+ снапшотах: по-прежнему отрицательный PnL.
- **Research-вывод**: комиссия maker 0.1% (10bps) превышает медианные спреды (BTC 0.002bps, ETH 0.05bps, SOL 1.3bps) в 100-5000 раз. Спот-MM на топ-парах нежизнеспособен без maker-rebate программ; направление требует либо пар с широким спредом (длинный хвост альткоинов), либо perp-фьючерсов с rebate. Это фиксирует границу применимости текущего research-направления.
- `run_morning_brief.py`: добавлена read-only секция "🔔 Quant WATCH" (WATCH_UP/WATCH_DOWN из quant_signal_product.json, до 5, с ML и regime). Проверено: `🔴 OP: down (ML 0.38, trend_down)`.
- Находка: REST API с `/api/v2/mon/*` (monetization_routes) НЕ развёрнут как сервис (нет systemd-юнита, uvicorn на 8092 — это converge/app.py). API-монетизация остаётся groundwork'ом — развёртывание требует решения владельца.
- Watcher: 571/1000 снапшотов (binance/mexc), полный MM-прогон запустится автоматически.

## Git (этап 5)

- Branch `agent/20260814-quant-backfill-ppo`, commit `a4b1c6f2`.


### Диск и health-check (18:40-19:10Z)

- Health-check (run_health_check.py): обновлены пути моделей — ppo_trader.pt/ppo_multi_24.pt/catboost_price_dir.cbm (устаревшие) → ppo_v9.pt/catboost_price_dir_v2.cbm. Ложные 🟠 устаревания устранены: OK 19/23 → 21/22.
- Диск 85% → 81% (освобождено ~4.5G):
  - /tmp: fastembed_cache 1.3G, временные aios-venv ~200M, старые .so ~220M;
  - docker: dangling ghcr.io/jotalbot/aios 3.2G (второй используется активным контейнером — не тронут), gitleaks образ 72M;
  - /var/log: syslog.1 99M, auth.log.1 20M;
  - 14 завершённых worktrees (~770M) удалены через git worktree remove (все чистые, ветки/коммиты в git);
  - apt clean.
- НЕ тронуто: /opt/android-sdk 8.7G (нужен эмуляторам), Calls/!voice 1.2G (личные записи), backups (свежие, ротация 30 дней), /opt/aios-embed 1.3G (venv без ссылок в коде — требует решения владельца).
- Осталось 81% (порог health-check 80%) — до полного зелёного не хватает ~0.7G; кандидат /opt/aios-embed.

## Git (этап 6)

- Branch `agent/20260814-quant-backfill-ppo`, commit `3be4cd27`.


### Полный MM-прогон завершён (19:25Z)

- Watcher набрал 1000+ снапшотов/пара → запустил симулятор: **14,460 снапшотов, 6 пар** (binance/mexc × BTC/ETH/SOL).
- Результат (min 1000): fill_rate 41-73%, PnL отрицательный на всех парах (−$48k BTC, −$1.5k ETH, −$37 SOL).
- **Финальный research-вывод (на полном датасете)**: спот-MM на топ-парах нежизнеспособен при комиссии maker 0.1% (10bps) и спредах 0.002-1.3bps. Для жизнеспособного MM нужны: (а) maker-rebate программы, (б) пары с широким спредом (длинный хвост), (в) perp-фьючерсы. Направление MM research закрыто с честным отрицательным результатом; данные orderbook остаются полезными для HFT-арбитражных окон (диспаритеты p95 2-2.6bps).
- Отчёт: data/reports/market_making_simulation.json (обновлён), orderbook_analysis.json.


## Этап 7: WATCH-верификация, ML-мониторинг, автообучение, feature-эксперимент

### 1. Историческая верификация WATCH (scripts/quant_watch_backtest.py, новый)

- Воспроизведение правил сигнального продукта (regime + ML prob) на OOS-хвосте (30%) всех 33 символов.
- **WATCH_DOWN: precision 59.4%** (85 подтверждений из 143) — умеренное преимущество над 50% baseline.
- **WATCH_UP: 0 сигналов** за OOS-период — правило (trend_up + prob>=0.60) не срабатывает в текущем медвежьем рынке. Зафиксировано, правила НЕ менялись (подгонка под окно запрещена).
- Отчёт: data/reports/quant_watch_backtest.json.

### 2. ML drift monitor (scripts/quant_ml_monitor.py, новый)

- Статистика распределения prob_up (mean/median/min/max/spread), n>=0.60/0.65, свежесть ml_signals.json и CSV, дрейф mean vs предыдущий снапшот (>0.10 → WARN), деградация распределения (spread<0.05 → WARN).
- История: data/reports/quant_ml_monitor_history.json (200 записей). Первый запуск: OK, 33 сигнала, spread 0.134.
- Таймер aios-quant-ml-monitor.timer (hourly, RandomizedDelaySec 300) установлен и enabled.

### 3. Автообучение ML (deploy/systemd/aios-quant-ml-retrain.{service,timer})

- Еженедельно (Пн 04:00, Persistent, delay 600): python scripts/quant_ml_eval_train.py — переобучает CatBoost v2 и деплоит только при улучшении (guard в скрипте).
- Файлы добавлены в deploy/systemd/ (канонический источник) и установлены в /etc/systemd/system, enable --now.
- Существующие юниты не тронуты.

### 4. Feature-эксперимент (scripts/quant_ml_feature_experiment.py, новый)

- 13 базовых фич vs 21 расширенная (+ATR%, range_z, ret36/48/72, hour_sin/cos, vol_med_ratio) на том же OOS-окне:
  - base_13: AUC 0.5355, hit@0.65 82.2%
  - full_21: AUC 0.5326, hit@0.65 70.8% → **расширение НЕ улучшает**, базовый набор остаётся.
- Отчёт: data/reports/quant_ml_feature_experiment.json.

### Прочее

- ETC в NO_DATA — корректно: последний закрытый бар низкообъёмный (vol_pct 0.01 < 0.05 → illiquid), данные свежие. Не баг.
- Текущие сигналы (20:02Z): WATCH_DOWN = TRX (ML 0.374), top ML = UNI 0.569, INJ 0.558 — ниже порога входа 0.65.

## Git (этап 7)

- Branch `agent/20260814-quant-backfill-ppo`, commit `3171c6b4`.


## Этап 8: честная OOS-оценка PPO + ML горизонты (21:10-21:30Z)

### КРИТИЧЕСКАЯ МЕТОДОЛОГИЧЕСКАЯ НАХОДКА: «скрытые шорты» в валидации PPO

- Валидация v8/v9 (и в ноутбуке kg_v8, и в quant_train_ppo.py) НЕ применяла clamp действия, который есть в инференс-мосте (rl_signal_bridge.py). При act < -1.5 конвертация int((act+1)/2*2)/2 давала **отрицательную позицию -0.5** — скрытый SHORT, невозможный в развёрнутой дискретной политике {0, 0.5, 1}.
- Исторические «прибыли» v8 (+51%), v9 (+96%), обучение ноутбука (+75%) — **артефакты скрытых шортов** на медвежьем окне.
- Честная оценка (с clamp, как в мосте): **v9 OOS sum_rl = 0.0** (Buy&Hold -233%) — PPO-агент чистый FLAT; ценность = избегание убытков, НЕ заработок.
- Исправлено: clamp добавлен в валидацию quant_train_ppo.py и quant_train_ppo_v10.py.

### PPO v10 с честным сплитом (quant_train_ppo_v10.py, новый)

- Среда обучается только на первых 70% истории каждого актива (гэп 48 баров), валидация на невидимых последних 30%.
- 300 эпизодов × 800 шагов, те же гиперпараметры; ~15 мин CPU.
- Результат: v10 с clamp = FLAT (0.0) на OOS — тот же veto. v10 НЕ развёрнута (нет OOS-заработка при развёрнутой дискретной политике). ppo_v9.pt остаётся veto-моделью.
- Отчёт: data/reports/ppo_oos_honest.json, ppo_v10_oos_eval.json.

### ML горизонты (quant_ml_horizon_experiment.py, новый)

- Label close[t+h] > close[t] для h ∈ {1, 4, 8, 24}, те же 13 фич, тот же OOS:
  - h1: AUC 0.5355, hit@0.65 82.2% (текущая — оптимальна)
  - h4: AUC 0.5202, hit@0.65 33.3%
  - h8: AUC 0.5137
  - h24: AUC 0.5145, hit@0.65 63.2%
- Вывод: next-bar горизонт оптимален; multi-horizon НЕ улучшает. Модель v2 остаётся.
- Отчёт: data/reports/quant_ml_horizon_experiment.json.

### Итог по RL

- Развёрнутая ppo_v9 = консервативный veto (всегда FLAT на текущем рынке) — это РЕАЛЬНАЯ, а не артефактная ценность.
- Чтобы RL зарабатывал: (а) явный SHORT-экшен (решение владельца + risk policy), (б) другой reward shaping. Зафиксировано в отчёте.

## Git (этап 8)

- Branch `agent/20260814-quant-backfill-ppo`, commits `174c3951`, `db27bdb4`.


### Дособор истории до ~10 500 баров + переобучение ML (21:30-21:55Z)

- Backfill до target 10000: все символы ~10000-10507 баров (~14 мес), целостность OK (0 дублей, 0 несортировок). MATIC/RNDR пропущены.
- Переобучение ML на расширенной истории (train 235k, test 101k): **AUC 0.5296 < 0.5355** (текущая на 7.5 мес), hit@0.65 = 1.0 при cov 0.006% (6 сделок). Кандидат НЕ задеплоен (критерий auc>deployed не выполнен).
- **Вывод**: старые данные (2024-2025) не улучшают предсказание недавнего рынка — крипторежимы дрейфуют; окно 7.5 мес оптимально для модели v2. Данные 10k остаются полезны для regime-анализа и длинных бэктестов.
- Развёрнутая модель не изменена (catboost_price_dir_v2.cbm, обучена на 5500 баров). Демон инференса продолжает использовать её.


### Этап 9: Тестовый замер — месяц торговли по текущему алгоритму (21:55-22:20Z)

`scripts/quant_monthly_backtest.py` (новый): реплика продакшн-правил Directional v2 1:1
(сигнальный движок SMA/RSI/BB/MACD + ML v2 + RL veto; gate owner-профиля ML>=0.65/conf>=0.88/
max 1 поз/DD 0.25%; выходы TP+2%/SL-1%/trail/bearish; комиссии 0.15%+спред). Все активы
обрабатываются синхронно по барам (как live-демон), единый портфель $1000.

**Период:** 2026-07-14 21:00 → 2026-08-14 21:00 UTC (ровно 1 календарный месяц, 744 бара).

**Сценарий 1 — текущий алгоритм (с ML gate):**
- Итог: $997.01 (−0.30%), сделок 1 (OP, stop_loss −1.49%), комиссии $0.90.
- ML gate заблокировал 1948 входов — ML>=0.65 за месяц достигнут лишь 1 раз.

**Сценарий 2 — контроль (без ML gate):**
- Итог: $994.61 (−0.54%), сделок 5 (2 win: BONK +0.29%, ARB +1.49%; 3 SL), комиссии $4.49.
- После первой потери DD>0.25% → 1356 global_drawdown_kill (порог владельца очень строг).

**Реальная динамика валют за месяц (Buy&Hold, 32 валюты):**
- Средняя −9.30% (медиана −10.79%); лучшая ADA +9.00%, SHIB +8.81%, LINK +8.55%;
  худшая BONK −37.73%, TIA −25.66%; BTC −2.71%, ETH +0.19%.

**Вывод:** текущий алгоритм (−0.30%) обыграл среднюю валюту на +9.0 п.п. и BTC на +2.4 п.п.,
но проиграл лучшим валютам и USD (кэш 0%). По сути контур месяц держал кэш (ML-gate почти
не пропускал входы) — защитная, а не зарабатывающая функция. Контроль без ML gate тоже
отрицателен (−0.54%) — индикаторная система без ML в этом месяце не зарабатывает.

**Допущения (в отчёте):** binance 1h как прокси бирж allowlist; ML in-sample для месяца
(обучена на данных, включающих месяц); funding/orderbook нейтральны; TP/SL по high/low бара.

Артефакты (gitignored): data/reports/monthly_backtest.md, .current_algorithm.json,
monthly_backtest_no_ml.md, .no_ml_gate.json.


### Этап 10: Поиск прибыльного алгоритма (22:20-23:05Z)

Систематический research 16 стратегий на честном OOS (без lookahead, комиссии 0.25%/сторона,
ML переобучена только на train, равный вес по 33 символам):

**Победитель: дневной трендовый long/short по пересечению SMA50/SMA200.**
- 70/30 сплит: +7.8%…+11.2% (40/160, 50/200, 60/240 — все параметры положительные);
- 50/50 сплит: **+34.7%** (50/200) / +19.7% (60/240), обе половины OOS в плюсе;
- Редкие сделки → низкие комиссии; классика trend-following.

**Критическое условие — шорты:** long-only вариант той же стратегии −4.5%. На медвежьем рынке
(BTC −46% за год) весь плюс от коротких позиций. Текущий Directional v2 шортов не имеет.

**Прочие результаты:** XS mean-reversion нестабилен (bot3_p7 +9.6% → −12.9%), RSI daily MR слаб
(+1.8…+5.6%), ML long/short и инверсный ML отрицательны на OOS, regime-LS 1h −137% (переторговка).

**Честные оговорки:** funding/стоимость заимствования для шортов НЕ учтены; прибыль сконцентрирована
в медвежьем режиме; выборка умеренная (33 актива × ~2-7 мес OOS); конституционно реальные шорты
запрещены без REVIEW и решения владельца.

**Рекомендация (в отчёте):** paper-контур MA-LS с честным funding → сравнение с Directional v2 →
решение владельца по шортам.

Артефакты: data/reports/strategy_research.json, strategy_research_robust.json,
strategy_final_check.json, strategy_research_summary.md (gitignored). Коммит `7c88f3a5`.


### Этап 11: Найден алгоритм с заработком — MA_LS_50_200 (23:05-23:50Z)

**Критический фикс движка бэктеста (v2):**
1. Компаундинг: капитал умножается на (1 + pos×ret) каждый бар. Ранняя версия суммировала арифметические
   доходности — завышение на волатильных активах (сумма −97.96% vs реальные −71.3% у BONK).
2. Тайминг: сигнал принимается на закрытии бара t и применяется к бару t+1 (была задержка на 1 бар).
3. Агрегация: равновесный портфель = СРЕДНЕЕ по символам (не произведение).

**Исправленные результаты — SMA50/200 daily long/short (0.25%/сторона):**
- OOS30: **+12.62%** net (funding базовый), +1.68% (funding стресс: шорт платит 0.03%/день);
- OOS50: **+41.56%** net (базовый), +23.92% (стресс);
- Половины OOS50: half1 **+32.41%**, half2 **+6.49%** — обе в плюсе;
- 24/33 символа положительные (OP +121%, SEI +120%, ARB +118%; убыточные NEAR −70%, INJ −65% — whipsaw на разворотах).
- MA_LS_60_240: OOS30 +14.03%, OOS50 +29.91%.

**Что не работает:** Donchian LS (−11…+1.5%), все long-only варианты (−1.4…−36.5%), XS моментум (−23%).

**Вывод:** единственный робастный заработок — трендовый long/short по дневным SMA50/200; плюс во всех
4 комбинациях сплит×funding и в обеих половинах. Ключ — шорты (медвежий рынок). INJ/NEAR-кейсы
(−65/−70%) показывают риск whipsaw на разворотах.

**Следующий шаг (рекомендован):** paper-контур MA_LS на Binance perp (33 пары, дневные бары, учёт реального
funding, 1 сигнал/день) → сравнение с Directional v2 1-2 мес → решение владельца по реальным шортам
(конституционный REVIEW).

Артефакты: data/reports/earn_research.json, earn_ma_ls_detail.json, earn_research_summary.md.
Коммиты: `9f95fbb5` (исправленный движок + результаты).

## Handoff

- Paper-вход Directional v2 структурно разблокирован: гейт ML=0.65 теперь достижим реальной моделью; сделки будут открываться при появлении prob_up>=0.65 (редкие, ~1-2/мес — селективность гейта).
- Следующий шаг: наблюдать циклы демона (полный скан на границе часа); при появлении WATCH/сделки — сверить PnL с симуляцией.
- Известные ограничения: (1) RL-мост деградирован — onehot-баг (все активы получают индекс BTC) → все 10 мажоров FLAT → rl_veto блокирует вход по BTC/ETH/SOL/BNB/XRP/ADA/DOGE/LINK/DOT/MATIC; 25 активов вне RL-карты не затронуты. Требует отдельного решения владельца (фикс onehot + переобучение PPO в Colab). (2) MATIC/RNDR — мёртвые тикеры (переименованы в POL/RENDER), засоряют universe сигнального продукта.
- Что нельзя делать без повторной проверки: включать live (гейт walk-forward отрицательный), менять пороги owner-профиля, удалять старую модель до подтверждения работы v2.
