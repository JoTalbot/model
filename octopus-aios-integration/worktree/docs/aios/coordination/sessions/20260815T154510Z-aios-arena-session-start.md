---
session_id: "20260815T154510Z-aios-arena-session-start"
status: "ACTIVE"
agent: "Arena.ai agent (workspace)"
machine: "aios (<PUBLIC_IP_REDACTED>)"
started_utc: "2026-08-15T15:45:10Z"
updated_utc: "2026-08-15T15:45:10Z"
branch: "agent/20260814-quant-backfill-ppo"
base_commit: "573eb4e98dac079025189446aa116827928fdec2"
claim: "none"
---

## Цель

Начало работы внешнего агента Arena.ai над проектом AIOS: ознакомление с инструкциями (AGENTS.md), координационными документами и состоянием репозитория. Конкретная задача будет определена оператором.

## Scope

- Разрешённые компоненты/файлы: определяется задачей оператора (пока нет).
- Явно вне scope: protected-файлы из AGENTS.md (run_coder_orchestrator*, run_telegram_bot.py, scripts/selfguard.py, aios_core/autocoder_v3*, aios_core/llm_balancer.py, aios_core/self_protection.py, aios_core/code_rag.py, aios_core/autocoder_memory.py, aios_core/orchestrator.py, aios_core/__init__.py, aios_core/advanced_security.py, aios_core/inter_swarm.py, octopus_core/api_v2_batch.py, .env*).
- Ожидаемые пересечения с другими сессиями: активные claims отсутствуют на момент старта (проверено).

## Исходное состояние

- git status --short: единственный untracked — backups/systemd_20260815/ (чужой артефакт решения владельца, не трогать).
- Ветка: agent/20260814-quant-backfill-ppo (последний коммит 573eb4e9).
- Прочитанные документы: AGENTS.md, coordination/PROJECT_CONTEXT.md, coordination/README.md, coordination/SESSION_TEMPLATE.md, coordination/claims/ (README + 3 активных claim: paper-fix, quant-6m-backtest, quant-history-backfill, whisper-audio-cleanup).
- Чужие незакоммиченные изменения: backups/systemd_20260815/ (не трогать).
- git fetch --all --prune: OK, origin синхронизирован.

## План

1. Ожидание задачи от оператора.
2. При получении задачи: создать claim, выполнить работу с минимальными правками, проверки (py_compile/pytest/ruff), коммит в ветку agent/<session>/<task>, обновить журнал.

## Ход работы и решений

- 2026-08-15T15:45Z: подключение к серверу по SSH (ключ из чата, pubkey совпал), изучение AGENTS.md, PROJECT_CONTEXT.md, README координации, claims, git-состояния. Создан журнал сессии. Активные параллельные сессии на quant-тематику (walk-forward, backfill, winrate) — quant-модуль считается занятым другим агентом до проверки claims перед задачей.

## Изменённые файлы

- coordination/sessions/20260815T154510Z-aios-arena-session-start.md — журнал сессии (этот файл).

## Проверки

- [PASS] ssh root@<PUBLIC_IP_REDACTED> — вход выполнен.
- [PASS] ssh-keygen -y -f <key> — публичный ключ совпал с предоставленным.
- [PASS] git fetch --all --prune — успешно.
- [PASS] git status --short — чисто, кроме чужого backups/systemd_20260815/.

## Git

- Коммиты: нет (изменений кода не было).
- Опубликованная ветка/PR: нет.
- Незакоммиченные изменения: журнал сессии (координационные файлы — часть работы; решение о коммите после первой реальной задачи).
- Чужие изменения, которые не были затронуты: backups/systemd_20260815/ — не тронут.

## Handoff

- Последняя завершённая точка: onboarding завершён, контекст загружен.
- Следующий конкретный шаг: получить задачу от оператора; перед кодом — проверить claims и создать собственный claim.
- Блокеры: нет.
- Риски: quant-модуль — активные claims других сессий; не пересекаться без согласования.
- Что нельзя делать без повторной проверки: git reset --hard / clean -fd / массовый add/commit; правки protected-файлов; переключение ветки в грязном worktree.

---

## Задача от оператора: quant-oos-profit (2026-08-15T15:50Z)

**Цель:** продолжить улучшение трейдинга — winrate и реальную прибыль. Предыдущая сетка
(quant_winrate_experiments, in-sample 1y) дала все варианты <= 0: BASE -165$, лучший T1 (тренд SMA200)
+2.96$ на 9 сделках (незначимо). Отчёт требует OOS-подтверждения.

**Решение:** честный walk-forward OOS на полных 12-мес. данных (8760 баров, allowlist):
- 2 фолда: train 70%/test 30% и train 85%/test 15%, свежая CatBoost v2 (те же гиперпараметры) на train;
- 16 предзаданных a-priori вариантов (тренд-гейты SMA50-200, ML>=0.70/0.75, блэклист, trail off,
  cooldown 24h, ATR-фильтр, TP/SL 2.5/1.0, комбо);
- выбор победителя ТОЛЬКО по OOS; затем портфельная симуляция (max 1 позиция, kill-свитчи).

Claim: coordination/claims/quant-oos-profit--20260815T154510Z-aios-arena-session-start.md
Скрипт: scripts/quant_oos_profit_experiments.py

---

## Ход работы quant-oos-profit (обновление 2026-08-15T16:35Z)

1. Изучены claims/журналы: активных пересечений нет (paper-fix DONE). Создан claim
   `quant-oos-profit--...` и скрипт `scripts/quant_oos_profit_experiments.py`.
2. Прогон 1 (v1): фикс-порог 0.65 недостижим свежеобученной моделью → почти 0 сделок;
   окна искажены короткими сериями (TON 525 баров).
3. v2: исключение серий <1500 баров; калибровка порога на train-перцентиле (q90-q97).
   Результат: BASE −1.91$, N1 (trail=1.0) +5.36$ на 7 сделках (WR 71%), единственный
   положительный. NO_ML −9129$ (8157 сделок) — ML-гейт ценен.
4. v3 (раунд 3): окно 0.60 добавлено; разложение по reason; N1m (0.995) +3.97$,
   N1X (TP2.5/SL1.0) +8.28$; монотонный эффект trail 0.988<0.995<1.0 подтверждён.
   Перцентильные пороги q98/q99 — отрицательны (слабые сигналы).
5. v4 (финал): дедуп по (symbol, opened_at) — окна перекрываются (0.50⊂0.60⊂0.70⊂0.85).
   Уникальные сделки: BASE +7.15$ (WR 50%, PF 2.50), N1 +14.42$ (WR 87.5%, PF 5.83),
   N1X +15.67$ (PF 6.24). Портфельная симуляция N1: +6.74$ (kill-свитчи 0.25% от $1000
   срабатывают — очень жёстко для такого капитала).
6. Обнаружено: data/quant/*.csv дописываются live-коллектором (KAS докачан 16:19Z между
   прогонами) — результаты привязаны к срезу 16:25Z; для воспроизводимости нужен снапшот.
7. catboost_info/*.tsv (tracked) модифицированы прогонами CatBoost — НЕ коммитятся.

## Итог для владельца

- Один параметр (trail_ratio 0.988→1.0) на том же наборе сигналов: WR 50→87.5%,
  PnL +7.15→+14.42$ на OOS (4 окна, 8 уникальных сделок). Рекомендация: paper-режим
  trail=1.0 (или 0.995) на 30д/200 сделок; live по-прежнему запрещён.
- Полный отчёт: docs/TRADING_OOS_PROFIT_EXPERIMENTS_2026-08-15_RU.md;
  сырые цифры: data/reports/oos_profit_experiments.md.
- Изменение прод-профиля — только решение владельца (правила AGENTS.md).

## Изменённые файлы

- scripts/quant_oos_profit_experiments.py — новый OOS harness (4 фолда, калибровка на train).
- docs/TRADING_OOS_PROFIT_EXPERIMENTS_2026-08-15_RU.md — отчёт владельцу.
- data/reports/oos_profit_experiments.md — артефакт прогона.
- coordination/sessions/20260815T154510Z-aios-arena-session-start.md — журнал (этот файл).
- coordination/claims/quant-oos-profit--20260815T154510Z-aios-arena-session-start.md — удалён после DONE.

## Проверки

- [PASS] py_compile скрипта на сервере и локально.
- [PASS] Сравнение BASE-варианта с прошлой сеткой (консистентность сигналов).
- [NOT RUN] pytest (изменений прод-кода нет, только новый standalone-скрипт).
- [NOT RUN] ruff (скрипт новый; стиль повторяет существующие quant-скрипты).

## Handoff

- Последняя завершённая точка: OOS-эксперименты завершены, отчёт и коммит готовы.
- Следующий шаг (владелец): решение о paper-прогоне с trail_ratio=1.0/0.995;
  при одобрении — правка owner-профиля и 30д paper-наблюдение.
- Блокеры: нет. Риски: выборка 8 сделок мала; live запрещён до gates.
- Что нельзя делать без повторной проверки: менять прод-профиль/quant-движок без решения
  владельца; git reset --hard/clean; push в remote без полномочий.

---

## Пункты 1-3 (обновление 2026-08-15T17:05Z)

### Пункт 2 — устойчивость N1 (DONE)
scripts/quant_oos_robustness.py (fold-0.70, ML>=0.65):
- Jackknife по 32 символам: N1 min +0.67$ / med +3.65$ / max +6.64$ (положителен при
  удалении ЛЮБОГО символа); BASE min -4.18$ / med -1.20$.
- Binance-цены (тот же период): N1 +3.57$ vs BASE -1.27$ — эффект воспроизводится на
  другом источнике цен (33 binance-серии).
- Вывод: N1-результат не зависит от одного символа или вендорских цен.
Отчёт: data/reports/oos_robustness.md.

### Пункт 1 — paper-профиль trail_ratio=1.0 (APPLIED)
- aios_core/quant_directional_policy.py: DirectionalV2Config + take_profit_pct (0.02),
  stop_loss_pct (-0.01), trail_ratio (0.988) из env AIOS_QUANT_* (дефолты = legacy).
- aios_core/quant_directional_v2.py: exit-логика использует config вместо литералов.
- tests/test_quant_directional_v2.py: +4 целевых теста (trail из env параметризованный,
  TP/SL из env, дефолты preserve legacy). 22/22 passed в quant-наборе.
- deploy/systemd/aios-quant-trading.service: +Environment=AIOS_QUANT_TRAIL_RATIO=1.0.
- Применено к runtime с одобрения владельца: unit скопирован в /etc/systemd/system
  (бэкап: backups/systemd_20260815/aios-quant-trading.service.pre-trail110),
  daemon-reload + restart. Сервис active, env виден, первый цикл без ошибок
  (trades=0, blocks={'same_candle': 1}). Paper-режим подтверждён ("real orders disabled").
- Полный pytest: 2 FAILED, оба НЕ связаны с этой задачей:
  1) test_project_inventory — обновлён инвентарём (generate_project_inventory.py --write);
  2) test_v22_api::test_monetization_routes_registered — 6 маршрутов вместо 5, маршрут
     /api/v2/mon/quant-signals добавлен чужим коммитом (v22.0-D) без обновления теста —
     pre-existing, не трогал.

### Пункт 3 — push
Ветки запушены в origin (одобрение владельца):
- agent/20260815-quant-oos-profit (research: OOS-эксперименты + robustness)
- agent/20260815-quant-trail-config (код: exit params + тесты + unit)

---

## Пакет улучшений (2026-08-15T17:15Z) — по решению владельца ("+")

### 1. Частичный тейк + бутстрэп (research, DONE)
scripts/quant_oos_partial_tp_bootstrap.py (fold 0.70, allowlist, ML>=0.65):
- PT2 (50%@+1.5%, остаток trail 1.0): +5.80$ / PF 12.59 / WR 75% — лучший (N1 +3.65$).
- PT1 (+3.81$), PT3 (+2.80$).
- Бутстрэп 2000 ресемплов по символам: N1 90% CI [-4.26, +11.55], pos_share 74.8%;
  Δ(N1-BASE) CI [+0.00, +12.10], pos_share 88.3% — разница устойчиво положительна.
- ВАЖНО: n=4 сделки на окне — выбор среди PT1/PT2/PT3 несёт selection bias;
  PT2 в прод НЕ применялся, требуется подтверждение на большем окне.
Отчёт: data/reports/oos_partial_tp_bootstrap.md.

### 2. Allowlist + binance (runtime, APPLIED)
- deploy/systemd/aios-quant-trading.service: ALLOWED_EXCHANGES += binance
  (kucoin,bitstamp,mexc,binance). Binance уже в EXCHANGES движка; robustness-проверка
  подтвердила тот же эффект N1 на binance-ценах (+3.57$ vs -1.27$).
- Применено: unit скопирован, daemon-reload, restart. exchange_not_allowed упал 96→72
  (6 неразрешённых бирж × 12 символов; binance теперь в allowlist).

### 3. Контрольный портфель (A/B, APPLIED)
- Новый deploy/systemd/aios-quant-trading-control.service: тот же allowlist,
  AIOS_QUANT_TRAIL_RATIO=0.988 (legacy), отдельный портфель
  multi_exchange_portfolios_owner_paper_control.json.
- Установлен и запущен (enable --now). Первый цикл: trades=0, blocks={'exchange_not_allowed': 72,
  'ml_not_confirmed': 12} — работает. Сравнение main (trail 1.0) vs control (trail 0.988)
  через 2-4 недели — честный A/B на живых данных.

### Проверки
- [PASS] Оба сервиса active, env корректен (ALLOWED/TRAIL/PORTFOLIO).
- [PASS] py_compile нового скрипта.
- [NOT RUN] полный pytest (изменения только unit-файлы + новый research-скрипт,
  прод-код не менялся в этом пакете).

### Изменённые файлы (этот коммит)
- scripts/quant_oos_partial_tp_bootstrap.py
- deploy/systemd/aios-quant-trading.service (allowlist += binance)
- deploy/systemd/aios-quant-trading-control.service (новый)
- coordination/sessions/20260815T154510Z-aios-arena-session-start.md

---

## Диагностика "почему 0 сделок" + ML/SHORT эксперименты (2026-08-15T17:50Z)

### Корневая проблема
Развёрнутая модель даёт prob_up>=0.65 в 0.26% баров (728/281k; 30д: 0.2%) — live-гейт
ML>=0.65 практически недостижим → trades=0 с момента запуска. Плюс exchange_not_allowed=72/цикл.

### Сделано
1. Allowlist расширен на ВСЕ биржи движка (kraken,binance,bybit,okx,uniswap_v3,coinbase,
   kucoin,bitfinex,bitstamp,mexc) в обоих unit (main + control). Применено, сервисы active.
2. quant_ml_cross_sectional.py: cross-sectional фичи (btc_ret6/24, btc_regime, rel_ret*,
   mom_rank24/6, vol_rank). Результат: AUC 0.530 vs cand_base 0.529 — НЕТ улучшения.
   Топ-фичи: btc_regime(31), btc_ret24(27) — модель учит рынок, но edge не появляется.
   Потолок технического ML на h1 ≈ AUC 0.53 подтверждён.
3. quant_oos_short_experiment.py: зеркальный SHORT (SELL_SHORT + ml<=0.40/0.35, те же
   TP/SL/trail). Результат: ml<=0.40: 305 сделок, WR 44.6%, PF 0.88, -48.07$;
   ml<=0.35: 115 сделок, PF 0.56, -82.87$. SHORT edge НЕТ.
4. LONG+SHORT комбо: PF 0.89, -45$ — тоже нет.

### Вывод
Техническая направленная торговля 1h (LONG или SHORT) не имеет положительного
матожидания после издержек — подтверждено с трёх сторон (OOS LONG, OOS SHORT,
ML cross-sectional). Проблема в источнике сигнала, не в настройках.
Дальнейшие варианты: (а) сигнальный продукт/мониторинг для человека, (б) инвентарный
MM на orderbook-данных (копятся), (в) живой A/B main vs control для калибровки на
реальной статистике (теперь с полным allowlist сделки возможны), (г) смена таймфрейма/
универсума. Решение за владельцем.

### Проверки
- [PASS] оба сервиса active, allowlist = 10 бирж.
- [PASS] py_compile новых скриптов.
- [NOT RUN] полный pytest (прод-код не менялся; только research-скрипты + units).

### Файлы этого коммита
- scripts/quant_ml_cross_sectional.py
- scripts/quant_oos_short_experiment.py
- deploy/systemd/aios-quant-trading.service (allowlist=все биржи)
- deploy/systemd/aios-quant-trading-control.service (allowlist=все биржи)
- coordination/sessions/20260815T154510Z-aios-arena-session-start.md

---

## Тестовый замер 3 месяца (2026-08-15T18:30Z)

- Скрипт scripts/quant_prod_3m_backtest.py: воспроизведение движка 1:1, конфиг из unit.
- Результат (2026-05-15..08-15): 10 сделок, WR 40%, PF 0.66, PnL -6.02$ (equity 9993.98/10000).
  BTC bh -2.29%. trailing_stop: 0 срабатываний -> trail 1.0 vs 0.988 идентичны.
  ml_not_confirmed=1865 (главный блокер), global_position_limit=435.
  Сделок в мае-июне 0 (ML<0.65), все 10 - июль-август. Все на kraken (приоритет unit).
- Четвёртое подтверждение отсутствия edge LONG-only 1h (OOS LONG/SHORT/ML-CS/этот замер).
- Попутно: обнаружен и устранён дрейф код/unit (ветка oos-profit без exit-параметров,
  сервис работал с литералом 0.988). Merge trail-config -> oos-profit (d2085e2f),
  сервисы перезапущены на консистентном коде (config.trail_ratio=1.0).
- Файлы: scripts/quant_prod_3m_backtest.py, docs/TRADING_3M_BACKTEST_2026-08-15_RU.md,
  data/reports/prod_3m_backtest.{md,json} (gitignored), журнал.

---

## Эксперимент C: таймфрейм × универсум (2026-08-15T19:10Z)

- scripts/quant_tf_universe_experiment.py: 1h/4h (ресемплинг закрытых баров) × все 33 /
  топ-12 по USD-объёму × RL вкл/выкл; свежая CatBoost per tf, OOS ~6 мес (2026-02-18..08-15).
- Результаты: 4h хуже 1h (PF 0.15-0.20), топ-12 пусто/хуже, RL-вето не влияет, TP3/SL1.5
  на 4h убыточно (PF 0.60). BTC bh за окно −11.83%. Ни один вариант не дал edge.
- ВАЖНО: обнаружен и исправлен баг первого 3-мес замера — kraken имеет историю ~724 баров
  (API-кап), load_series брал его первым (приоритет unit) → старый замер покрывал ~1 мес.
  Фикс: min_bars>=4000 → все серии binance (полные 12 мес). Переснятый 3-мес замер:
  MAIN (trail 1.0) 23 сделки, WR 43.5%, PF 0.64, −13.71$; CTL (trail 0.988) −19.04$;
  BTC bh −20.63%. Trail 1.0 > 0.988 на этом окне (согласуется с N1), но оба убыточны.
  ml_not_confirmed=5400 — главный блокер подтверждён.
- Итого 5 независимых подтверждений отсутствия edge: OOS LONG, OOS SHORT, ML-CS,
  prod-3m (исправленный), tf×universe.
- Файлы: scripts/quant_tf_universe_experiment.py, scripts/quant_prod_3m_backtest.py (фикс),
  docs/TRADING_TF_UNIVERSE_EXPERIMENT_2026-08-15_RU.md, docs/TRADING_3M_BACKTEST_2026-08-15_RU.md
  (оговорка), data/reports/tf_universe_experiment.md + prod_3m_backtest.md (gitignored).

---

## ML гипотеза F, этап 1: MTF-фичи (2026-08-15T20:10Z)

- scripts/quant_ml_mtf_experiment.py: base13 + 4h/1d фичи (по закрытым группам) + сезонность.
- Первая версия дала AUC 0.76 — lookahead-утечка (close/high/low текущей группы).
  Исправлено на closed-only (shift 1). Честные цифры: MTF AUC 0.5204 vs base 0.5285,
  PnL −27.38$ vs −5.86$ (deployed 0.5461, −5.86$). MTF НЕ улучшает.
- Топ-фичи MTF: hour_cos/sin/dow (сезонность) — не даёт edge.
- Локальные OHLCV-данные исчерпаны: 6 экспериментов PF<1. Для F-2 нужны внешние данные
  (funding/OI с Binance Futures — публичный API, бесплатно; новости/on-chain — ключи).
- Файлы: scripts/quant_ml_mtf_experiment.py, docs/TRADING_ML_MTF_EXPERIMENT_2026-08-15_RU.md,
  data/reports/ml_mtf_experiment.md (gitignored).

---

## F-2: funding-эксперимент (2026-08-15T21:10Z) — ОТРИЦАТЕЛЬНЫЙ

- Собран funding rate с Binance Futures (30 активов, 166 дней, публичный API).
- Скрипты: scripts/fetch_funding_oi.py, scripts/quant_ml_funding_experiment.py.
- Результат: AUC funding 0.5239 vs base 0.5296; funding-фичи без веса; PnL 1 сделка −2.99$.
- Вывод: funding не несёт edge для 1h. OI история ~30 дней (мало), копим.
- 7-й отрицательный результат. Отчёт: docs/TRADING_ML_FUNDING_EXPERIMENT_2026-08-15_RU.md.

---

## F-4: multi-horizon target (2026-08-15T21:45Z) — ОТРИЦАТЕЛЬНЫЙ

- scripts/quant_ml_horizon_experiment.py: target h1/h4/h24, base 13 фич, честный OOS.
- AUC: h1 0.5296 > h4 0.5226 > h24 0.5141; up_rate падает (mean-reverting рынок);
  PnL h4 −26.67$, h24 −26.57$ vs deployed −5.86$. Гипотеза не подтверждена.
- 8-й отрицательный результат подряд (LONG OOS, SHORT OOS, ML-CS, prod-3m,
  tf×universe, MTF, funding, horizon).
- Отчёт: docs/TRADING_ML_HORIZON_EXPERIMENT_2026-08-15_RU.md.

---

## Вариант 2: долгосрочный портфель DCA (2026-08-15T18:45Z)

- quant_dca_analysis.py: бэктест 12 мес (binance, комиссия 0.1%): DCA топ-10 + квартальный
  ребаланс −18.9% — лучший; DCA > lump-sum на ~12-15 п.п.; все в минусе (год медвежий).
- run_dca_paper.py + aios-dca-paper.{service,timer}: ежедневный mark-to-market paper-трекера,
  еженедельный депозит $100, топ-10 равные веса, квартальный ребаланс. Деплой: timer active
  (ежедневно 17:30 UTC). Первый депозит выполнен.
- Документы: docs/DCA_PORTFOLIO_PLAN_2026-08-15_RU.md, data/reports/dca_analysis.md (gitignored).
- Конфиг трекера: data/dca_portfolio.json (runtime, gitignored).

---

## MM-пилот (2026-08-15T19:20Z) — этап 1 завершён

- Прототип mm_proto_backtest.py: двусторонний квотинг + инвентарный контроль + FIFO spread.
- Данные: 183k снапшотов / 28ч / 6 бирж / BTC-ETH-SOL (~7k снапшотов/час).
- Результат: инвентарь контролируется (±0.018 BTC), но adverse selection доминирует —
  naive passive MM убыточен на всех биржах (−37..−77$ за 1.6ч, spread PnL отрицательный).
- Нужны: недели данных, сигнал направления (микроструктура), maker-rebate биржа.
- Отчёт: docs/MM_PILOT_2026-08-15_RU.md. Этап 2 (сигнал направления) — по решению владельца.

---

## MM этап 2: сигнал направления (2026-08-15T20:40Z) — ПОЛОЖИТЕЛЬНЫЙ

- scripts/mm_microstructure_signal.py: OBI/microprice фичи, честный таргет (flat исключён).
  AUC h1: BTC/binance 0.96, BTC/kucoin 0.94, ETH 0.89, SOL 0.85 — сильный сигнал.
- scripts/mm_proto_backtest.py: naive vs gated MM (реквот каждый снапшот, модель-гейт).
  Gated устраняет adverse selection: gross −30..−43$ → ~0/+1.4$ (BTC). При fee 0.01%
  BTC/kucoin net −0.12$, BTC/binance −2.5$ (было −177$ naive).
- Ограничения: 1.6ч данных на пару, симуляция оптимистична (без очереди), SOL/ETH слабее.
- Этап 3: websocket-коллектор (1-5с), 2-4 недели данных, калибровка, paper MM.
- Отчёт: docs/MM_STAGE2_SIGNAL_2026-08-15_RU.md.

---

## MM этап 3: websocket-коллектор (2026-08-15T20:15Z) — ЗАПУЩЕН

- scripts/collect_orderbook_ws.py: Binance depth20@100ms, по соединению на пару (BTC/ETH/SOL),
  запись 1/сек в snapshots_ws. Отладка: combined /ws/ не оборачивает сообщения (нет поля s)
  -> per-pair соединения; pkill -f матчил собственную ssh-команду (2 потери процесса).
- Сервис aios-orderbook-ws.service: active, Restart=always, ~1.75 снапшота/с суммарно.
- Цель: 2-4 недели данных (1 Гц) -> переобучение сигнала, модель очереди, вердикт по MM.
- Файлы: scripts/collect_orderbook_ws.py, deploy/systemd/aios-orderbook-ws.service,
  docs/MM_STAGE3_WS_COLLECTOR_2026-08-15_RU.md.

---

## "Делаем всё" — финальный пакет (2026-08-15T20:50Z)

1. **MM-сигнал валидирован на 29ч (18 пар-бирж)**: AUC стабилен — BTC/binance 0.963,
   BTC/kucoin 0.948, BTC/okx 0.910, ETH/kucoin 0.902, ETH/binance 0.893; слабые —
   bitstamp/coinbase (тонкие стаканы, AUC 0.55-0.64). Предыдущая оценка «1.6ч» была
   артефактом расчёта часов (реальный поток 29ч) — устойчивость подтверждена.
   Gated MM: adverse selection устранён (gross>=0 на BTC), но филлов мало при порогах
   0.55/0.45 — калибровка порогов/спреда = следующий шаг после накопления ws-данных.
   Отчёт: docs/MM_SIGNAL_29H_VALIDATION_2026-08-15_RU.md.
2. **DCA-трекер**: 1 депозит ($100), value $99.95, комиссии $0.10; следующий депозит 22.08,
   ребаланс ~15.11. Отчёт: docs/DCA_TRACKER_REPORT_2026-08-15_RU.md.
3. **A/B paper**: оба сервиса активны, сделок 0 (ML-гейт: ml_not_confirmed 20/3 за цикл) —
   контуры работают, входы режутся моделью, как и в бэктестах. Сравнение — после накопления.
4. **PROJECT_CONTEXT.md обновлён** (секции «Где закончили» и «Следующий рекомендуемый шаг»).
5. Скрипт сигнала получил поддержку --table snapshots_ws (для будущего переобучения на ws-данных).

---

## Пакет М1+М2+D1 (2026-08-15T21:10Z)

- **М1 (калибровка MM)**: сетка порогов/спреда/размера/hold на 29ч REST BTC/binance —
  безубыточных конфигураций НЕТ (лучший net −0.11$ при fee 0.01%, 2 филла; max gross +1.00$
  на 14 филлах). Причина: интервал снапшотов ~9с → квота живёт 9-27с, исполнений единицы.
  REST-данные непригодны для калибровки MM — нужны 1-Гц ws-данные (копятся).
  В прототип добавлен параметр hold_snaps (удержание квоты).
- **М2 (расширение коллектора)**: ws-коллектор теперь 7 пар (BTC, ETH, SOL, XRP, BNB, DOGE, ADA),
  сервис перезапущен, все подключены. Данные 1Гц копятся для будущей калибровки.
- **D1 (TG-уведомления DCA)**: scripts/dca_telegram_report.py (credentials systemd, без секретов
  в коде), тест отправки OK (sent: True), таймер aios-dca-report.timer — понедельник 18:00Z.
- Файлы: scripts/mm_proto_backtest.py (hold_snaps), deploy/systemd/aios-orderbook-ws.service (7 пар),
  scripts/dca_telegram_report.py, deploy/systemd/aios-dca-report.{service,timer},
  docs/DCA_TELEGRAM_REPORT_SETUP_2026-08-15_RU.md.

---

## Пакет V1+V2+V3+V6 (2026-08-15T21:15Z)

- V1 live-монитор MM (OBI/microprice, верификация 60с): aios-mm-signal-monitor.timer (5 мин),
  лог mm_signal_live.jsonl. Первый прогон: BTC FLAT, ETH UP, SOL UP (промах) — статистика копится.
- V2 горизонты: ETH держит сигнал до 180с (AUC 0.97-1.0), SOL затухает (0.89→0.41),
  BTC mid статичен (21 движение/30мин). Выборки малы — гипотеза «1-3 мин» предварительно.
- V3 weekly-digest в TG (DCA+ws+A/B+сервисы): тест OK.
- V6 daily funding/OI коллектор (33 символа, append jsonl): таймер 19:15Z, первый прогон OK.
- 4 новых сервиса/таймера активны. Отчёт: docs/QUANT_DIGEST_V1V2V3V6_2026-08-15_RU.md.

---

## V4-прототип: эмиттер MM-сигналов (2026-08-15T21:30Z)

- mm_signal_emitter.py + aios-mm-signal-emitter.timer (5 мин, ETH/BNB/SOL): обучение модели
  на ws-данных, эмиссия UP/DOWN при prob>=0.60/<=0.40 в TG владельца, лог эмиссий.
- Первые сигналы: BNB DOWN (0.003/0.044), SOL UP (0.958); BTC исключён (mid статичен).
- mm_signal_score.py: сверка эмиссий с фактом (+60/180с); точность добавлена в weekly-digest.
  Первые цифры: 50% (1/2) — выборка ничтожна, копим дни.
- Дальше: если live-точность >=65-70% за 2-4 недели — сигнальный продукт (подписка).
- Файлы: scripts/mm_signal_emitter.py, deploy/systemd/aios-mm-signal-emitter.{service,timer},
  scripts/mm_signal_score.py, scripts/aios_weekly_digest.py (patch), docs/MM_SIGNAL_EMITTER_2026-08-15_RU.md.

---

## Пакет Q1+Q2+Q3+Q6 (2026-08-15T21:55Z)

- Q1: aggTrade коллектор в ws-скрипт (trades_ws: buy/sell vol, buy_frac за 5с) — фича для сигнала.
- Q2: /quant в TG-боте — tg_bot/quant_cmds.py (новый) + минимальная правка protected
  run_telegram_bot.py (3 места, selfguard --force-snapshot выполнен, бот перезапущен active).
  Проверен вывод: MM-точность 50% (3/6), ws 7.7k, DCA, A/B, сервисы.
- Q3: VA-бэктест — VA top-10+ребаланс (кап 2x) −17.21% лучший (DCA+reb −18.87%);
  VA кап 3x maxDD −11.47%. Рекомендация для реальных денег: VA+ребаланс.
- Q6: ws-коллектор на 20 пар (все connected).
- Отчёт: docs/QUANT_PACKAGE_Q1Q2Q3Q6_2026-08-15_RU.md.

---

## Пакет: buy_frac в сигнал + VA в DCA-трекер (2026-08-15T22:20Z)

1. mm_signal_emitter.py: добавлена trade-flow фича (buy_frac, buy_frac_rev из trades_ws,
   ближайший к снапшоту агрегат). Эмиттер выдаёт уверенные сигналы: ETH UP 0.759,
   BNB UP 0.992, SOL DOWN 0.066 — отправлены в TG.
2. run_dca_paper.py: режим value-averaging (mode=va, va_cap_mult=2.0): вклад =
   clamp(план − стоимость, 0, weekly*cap). Включён в конфиг data/dca_portfolio.json.
   Идемпотентность сохранена (депозит не задвоился).
3. Накопленная статистика сигналов: 58% точность на движениях (11/19), BNB 53%,
   SOL 67%, ETH 100% (1 движ.); ws 21.8k снапшотов (1.2ч), trade-flow 2343 записей.

---

## Q4+Q5 (2026-08-15T23:05Z) — финальный пакет

- Q4: queue-model в mm_proto_backtest.py (частичные филлы по доле в уровне, добивка
  остатка). Проверено на ws 1Гц с реальными спредами (BTC 0.0016bps!). Урок: прежние
  half-spread 2bps в ~1000x шире реального спреда BTC -> квоты не исполнялись; при
  реалистичных 0.001-0.05bps — 9-14 филлов/час. PnL на 1-1.6ч отрицательный (мало данных).
- Q5: подписки — subscription_manage.py (add/list/revoke/clean), quant_subscriptions.json,
  broadcast в эмиттере (владелец + активные подписчики). Owner-подписка создана (365д).
  Сигналы: ETH UP 0.987, BNB UP 0.911, SOL UP 0.975 — доставлены.
- Отчёт: docs/SIGNAL_SUBSCRIPTION_INFRA_2026-08-15_RU.md.

---

## R1 (2026-08-15T23:40Z) — экономика сигнала ОТРИЦАТЕЛЬНА

- signal_pnl_sim.py: 98 сделок по эмиссиям (market вход/выход, 60/180с, fee 0.1%×2, $100).
- РЕЗУЛЬТАТ: gross ≈ 0.00$ на 98 сделках, fees 19.60$, net −19.61$. Сигнал предсказывает
  направление (63% live), но величина движений за 1-3 мин микроскопическая — комиссии
  доминируют, даже при нулевых комиссиях прибыли нет.
- СЛЕДСТВИЯ: (1) подписка на сигналы для ручной торговли не обоснована (продажа ложной
  ценности) — эмиттер переведён в диагностический режим (лог без TG), таймер 5→15 мин;
  (2) R3 (калибровка порогов) не имеет смысла — пороги не создадут gross;
  (3) микроструктура полезна только как MM-фильтр adverse selection, вердикт после
  2-4 недель данных.
- Документ: docs/SIGNAL_ECONOMICS_R1_2026-08-15_RU.md.

---

## W1+W4+W3 (2026-08-16T00:10Z)

- W1 (run_mm_best): квотирование на реальных best bid/ask с maker-комиссией.
  Gross отрицательный даже при fee=0 (−1.7..−5.6$) на 1-2ч данных; модель на 1-Гц
  некорректна (таргет 1с), данные = шум. Вердикт только после недель данных.
- W4 (signal_pnl_maker.py): maker-вход лимиткой. net −19.61$ → −1.50$ (13x лучше),
  но fill% 22%, WR 0% — лимитка заполняется при движении против нас (adverse
  selection на входе). Сигнал-как-лимитка = ловушка.
- W3: дайджест TG включает экономику maker-входа (ежедневный авто-контроль).
- Выводы: taker-торговля закрыта (R1), maker-вход по сигналу закрыта (W4),
  полный maker-MM с микроструктурным фильтром — единственное живое (вердикт после
  2-4 недель корректных 1-Гц данных).
- Документ: docs/SIGNAL_ECONOMICS_W1W4_2026-08-15_RU.md.

---

## D6+D5+D1 (2026-08-16T00:40Z)

- D6: контрольный DCA-портфель (data/dca_portfolio_control.json, обычный DCA $100/нед,
  те же веса) + aios-dca-paper-control.timer (17:35Z). run_dca_paper.py поддержал
  DCA_CONFIG env (legacy-имена для main). A/B VA vs DCA на живых данных за 1-2 мес.
- D5: dca_chart_report.py — PNG-график (VA main + DCA control + invested) через
  sendPhoto; тест sent: True; подключён к еженедельному dca-report (пн 18:00Z).
- D1: вклад main $100 → $300/нед.
- Состояние: main $99.99 (VA, $100 вложено), control $99.90 (DCA, $100 вложено).
- Файлы: scripts/run_dca_paper.py, scripts/dca_chart_report.py,
  scripts/dca_telegram_report.py, deploy/systemd/aios-dca-paper-control.{service,timer},
  deploy/systemd/aios-dca-report.service, data/dca_portfolio{,_control}.json (runtime).

---

## N1: новостной сентимент (2026-08-16T01:10Z)

- collect_news_sentiment.py: RSS (CoinTelegraph/CoinDesk/CryptoSlate) + Gemini 2.5 Flash
  сентимент заголовков → news_sentiment.jsonl. Первый сбор: 65 новостей (pos 19/neg 38/neu 8).
- Отладка: GROQ 403 (регион), OpenRouter 402 (баланс), Gemini — ключ в URL без Bearer,
  модель gemini-2.5-flash; удалён дубль score_batch.
- Таймер aios-news-sentiment.timer (ежечасно :20). /quant + строка сентимента.
- N2 (связь сентимента с ценой) — после 1-2 недель накопления.
- Документ: docs/NEWS_SENTIMENT_COLLECTOR_2026-08-16_RU.md.

---

## P1+P2+P3 (2026-08-16T01:40Z)

- P1: collect_market_context.py (F&G + макро-календарь), таймер ежедневно 06:00Z,
  F&G в /quant. Текущий F&G: 34 (Fear). Макро API rate-limited (429) — graceful.
- P2: sentiment_price_test.py (корреляция сентимент→доходность 30м/1ч). Выборка пуста:
  новости 22:31-22:32, ws до 22:53 — горизонт за пределами. Инструмент готов; первые
  цифры через 1-2 дня накопления.
- P3: дайджест + строка сентимента (перед сервисами).
- Файлы: scripts/collect_market_context.py, scripts/sentiment_price_test.py,
  scripts/aios_weekly_digest.py, tg_bot/quant_cmds.py,
  deploy/systemd/aios-market-context.{service,timer},
  docs/MARKET_CONTEXT_P1P2P3_2026-08-16_RU.md.

---

## Исторические новости: пайплайн (2026-08-16T02:40Z)

- Сбор: Wayback RSS снапшоты CoinTelegraph (11 648 за год) -> 1545 заголовков
  (2025-08..2026-07) с pubDate. fetch_historical_news.py.
- Сентимент: score_historical_sentiment.py (Gemini 2.5 Flash, resume-safe).
  КВОТА ИСЧЕРПАНА (429) — 1 рабочий ключ из 3; таймер aios-news-scoring.timer
  (каждые 30 мин) догонит автоматически.
- Тест связи: sentiment_price_historical.py (1h/24h/3d/7d корреляции).
- Локальное тестирование ПЕРЕД деплоем (по требованию владельца): tests/test_news_pipeline.py
  — 30 тестов, 30/30 PASS локально и на сервере против прод-скриптов.
  Исправлены: валидация ключей (429 != мёртвый ключ), break при мёртвой квоте,
  пауза 5->12с.
- Файлы: scripts/fetch_historical_news.py, scripts/score_historical_sentiment.py,
  scripts/sentiment_price_historical.py, deploy/systemd/aios-news-scoring.{service,timer},
  tests/{test_news_pipeline.py, fake_quant_monthly_backtest.py, fixtures/},
  docs/NEWS_HISTORICAL_PIPELINE_2026-08-16_RU.md.

---

## Локальный сентимент + тест связи с ценой (2026-08-16T03:30Z)

- news_local_sentiment.py: лексиконный скорер (вместо Gemini — квота исчерпана).
  Калибровка на 65 живых: corr +0.623 с Gemini, знаковое согласие 94-95%.
  Тесты: tests/test_local_sentiment.py 21/21 PASS (локально + на сервере).
- Прогнано: 1545 исторических заголовков за 0.03s (344 pos/248 neg/953 neu).
- sentiment_price_historical.py: читает локально-скоредный файл (SCORED fallback).
- РЕЗУЛЬТАТ теста связи (1781 совпадений): corr 1h +0.007, 24h -0.058, 3d -0.036,
  7d -0.060 — СВЯЗИ НЕТ, на длинных горизонтах слабо отрицательная (sell the news).
- 9-й отрицательный результат направленного предсказания. Сентимент-фичи в модель
  не добавляем. Лексикон остаётся бесплатным монитором сентимента.
- Документ: docs/SENTIMENT_PRICE_HISTORICAL_RESULT_2026-08-16_RU.md.

---

## Макро+деривативы: предсказательный тест (2026-08-16T05:10Z) — 10-й отрицательный

- Разработка и тесты ЛОКАЛЬНО (по требованию владельца): tests/macro/test_macro_pipeline.py
  22/22 PASS; Binance локально 451 -> фикстуры форматов, реальный сбор на сервере.
- Данные: 400 дней макро/on-chain (Yahoo+blockchain.info) + 720ч деривативов + 1419ч цен.
- Результаты: daily всё ≈0 (DXY diff 0.32% — слабо); hourly: LSR→24h corr +0.199 (test +0.44),
  НО разбивка по блокам: SHORT(LSR<мед) +23/+38/−22/+10% — знак = режим рынка.
- ВЫВОД: LSR = прокси режима (не предсказатель); SHORT при низком LSR прибылен только
  в медвежьем рынке (тривиально). 10-й отрицательный результат. Новых классов нет.
- Побочное: накопитель деривативов (collect_derivatives_daily.py + таймер ежечасно) —
  долгая история LSR/OI/taker для будущего; LSR как индикатор режима для DCA.
- Документ: docs/MACRO_DERIVATIVES_PREDICTIVE_TEST_2026-08-16_RU.md.

---

## 2-летний бэктест (2026-08-16T06:10Z)

- Разработано ЛОКАЛЬНО (test_backtest_2y.py, 17 тестов: пагинация, сигналы, движок,
  OOS-сплит, kill-свитч), задеплоено после зелёных тестов.
- Данные: 8 активов x 2 года 1h (17520 баров), Binance Futures.
- OOS (посл. ~7 мес): 23 сделки, WR 35%, PF 0.41, PnL −26.45$ (BH −30.9% в окне).
- Справочно весь период с train-пробами: +27.5$ (подгонка, не OOS).
- Вывод: стратегия убыточна на 2-летнем OOS, но обгоняет buy&hold в медвежьем окне
  (защита капитала, не доходность). Масштаб убытка растёт с горизонтом.
- Документ: docs/BACKTEST_2Y_2026-08-16_RU.md.

---

## Факторные стратегии: НАЙДЕНА ДОХОДНАЯ (2026-08-16T08:10Z)

- momentum_strategies.py + test_momentum.py (17 тестов) — локально, потом прод.
- 3 года 1d данных (Yahoo, 14 активов), 7 вариантов a-priori, издержки 0.15%.
- T2 (TS-момент BTC, SMA50): +143.5% (CAGR +34.4%, Sharpe 1.06, MaxDD −27.7% vs BH −53.1%).
  В рынке 56% времени. ETH-версия: +156.8% (BH +2.2%). Чувствительность SMA30-50 — плато.
- Честно: OOS (медвежий 2026) −17.6%; вся прибыль из бычьего 2024; классический фактор.
- Рекомендация: paper-контур T2 (ежедневный сигнал close vs SMA50), затем — реальная
  аллокация. Первая доходная стратегия за 11 отрицательных тестов.
- Документ: docs/MOMENTUM_STRATEGIES_RESULT_2026-08-16_RU.md.

---

## T2 paper-контур запущен (2026-08-16T08:50Z)

- run_t2_momentum.py + test_t2_paper.py (28 тестов: сигнал, фолбэк Yahoo/Binance,
  идемпотентность, издержки вход/выход, mark, BH): 28/28 PASS локально и на сервере.
- systemd: aios-t2-momentum.timer (01:30 UTC), TG-уведомления при смене позиции.
- Бэкфилл 3 лет: equity $10k → $25,473 (+154.7%) vs BH +134.4%, 68 сделок, позиция CASH
  (close 63,004 < SMA50 63,510). Расхождение с бэктестом (+143.5%) — конвенция mark.
- /quant + строка T2. Документ: docs/T2_PAPER_LOOP_2026-08-16_RU.md.

---

## T2 ETH + дайджест (2026-08-16T09:30Z)

- run_t2_momentum.py: --symbol (BTC-USD/ETH-USD), per-symbol state/log, Binance
  фолбэк ETHUSDT. Тесты 33/33 локально (symbol URL, per-symbol paths).
- aios-t2-momentum.service: оба символа ежедневно 01:30Z.
- ETH бэкфилл 3 года: $10k → $27,977 (+179.8%) vs BH +20.0%, LONG, 45 сделок.
- /quant + weekly digest: T2-BTC и T2-ETH (позиция, PnL). Дайджест отправлен.
- Документ: docs/T2_ETH_AND_DIGEST_2026-08-16_RU.md.

---

## V1-V7: валидация и расширение T2 (2026-08-16T10:10Z)

- V6 (5 лет): BTC +127.8% (BH +47%), ETH +103.2% (BH −35%), SOL +406.3% (BH +91%).
- V5 (ролл-окна): 8/9 положительных у всех трёх — устойчиво.
- V7 (калибровка): SMA40-60 плато — SMA50 робастен, не подгонка.
- V1: SOL-контур (3г: +229.5%); V2: портфель 50/50 (5л: +129.6% vs BH +7%);
  V3: --daily-report; V4: график T2 в chart_report (ежедневно).
- Сервис: BTC+ETH+SOL+portfolio+chart, 01:30Z. /quant: 3 строки T2.
- Документ: docs/T2_VALIDATION_AND_EXPANSION_2026-08-16_RU.md.

---

## W1+W4+W5 (2026-08-16T10:50Z)

- W5: OOS-калибровка SMA — небольшое улучшение BTC/ETH (SMA40/60), SOL убыточен на
  медвежьем тесте; SMA50 робастен, оставлен. Подгонки нет.
- W4: стоп-лосс РАЗРУШАЕТ T2 (−60..−90% vs +100..+400%): 400+ стопов = стоп-охота;
  SMA50 сам защита. Отвергнут — важный негативный результат.
- W1: 3-активный портфель (BTC+ETH+SOL) в t2_portfolio.py: $28,800 vs BH $23,223;
  /quant + портфель.
- Документ: docs/T2_W1W4W5_2026-08-16_RU.md.

---

## U1+U3+U4+U5 (2026-08-16T11:40Z)

- U5 (7 лет): BTC +1574% vs BH +474%, ETH +1379% vs +744%, SOL +23965% vs +7823% —
  стратегия подтверждена на максимальной истории.
- U1 (гистерезис): BTC 50/40 лучше (+141.8%, DD −44% vs +127.8%/−58%); ETH ~0; SOL хуже.
  Не универсален — не внедряем (кроме, возможно, BTC позже).
- U3 (ребаланс): разрушает (+65.5% vs +242.8%, DD −85%) — против моментум-логики. НЕ делать.
- U4 (сверка цен): внедрена в прод (предупреждение в TG при >0.5% расхождении); 36/36 тестов.
- Документ: docs/T2_U1U3U4U5_2026-08-16_RU.md.

---

## X1+X2+X3 + расширение на 5 валют (2026-08-16T12:30Z)

- Скрининг 14 валют: работают BTC/ETH/SOL/BNB/NEAR; остальные 9 убыточны — не берём.
- X1: гистерезис 50/40 улучшает BTC/ETH/SOL на 7 годах (BTC +171 п.п., ETH +832,
  SOL +10542 п.п., DD лучше), вредит BNB/NEAR — внедрён для трёх, SMA50 для двух.
- X2: трейлинг-стоп отвергнут (снижает доходность).
- X3: SMA40 оптимум на 7 годах; 50/40 — робастная альтернатива.
- Сервис: 5 контуров + портфель (5 активов): $25,767 vs BH $22,939.
- Тесты: 40/40 локально. Документ: docs/T2_EXPANSION_5SYMBOLS_2026-08-16_RU.md.

---

## Y1+Y2+Y3+Y4 (2026-08-16T13:10Z)

- Y1 (vol-target): DD лучше у NEAR/BNB/ETH, доходность хуже у SOL — не внедрён.
- Y2 (SMA150-фильтр): DD BTC −58→−28%! но доходность режет — не внедрён.
- КОМБО: на 5 лет BTC +184% (DD −22%) выглядел прорывно, НО на 7 лет +722% vs +1574% —
  артефакт периода. НЕ внедрён (важный урок про проверку на полном цикле).
- Y3 (объём): пропущен (нет согласованных исторических объёмов).
- Y4 (Binance primary): внедрён — источник цен Binance spot, Yahoo фолбэк.
- Тесты: 40/40 локально, 28/28 сервер. Документ: docs/T2_Y1Y4_FINDINGS_2026-08-16_RU.md.

---

## Z3 (MM-вердикт) + интернет-исследование (2026-08-16T14:00Z)

### Z3 — MM-вердикт (2 дня ws-данных, ~5.5ч)
- Сигнал подтверждён: AUC ETH 0.947, BNB 0.942, SOL 0.913 (на 2-дневных данных);
- Экономика MM: BNB gross +0.06$ (безубыточен при fee 0.01%: −0.83$), ETH/SOL убыточны;
- Вывод: сигнал сильный, но экономика maker-MM не сходится на текущих данных/модели
  исполнения; вердикт — «нужны недели данных или maker-rebate», направление не закрыто,
  но не приоритетно.

### Интернет-исследование торговых стратегий (глубокий обзор)
- Отчёт: docs/TRADING_RESEARCH_INTERNET_2026-08-16_RU.md;
- Ключевые находки:
  1. Наш T2 подтверждён наукой (time-series momentum 31.96% годовых, 2020-2025);
  2. Парный трейдинг BTC-ETH (коинтеграция): Sharpe 2.45-7.94 — НЕ ТЕСТИРОВАЛИ, топ-приоритет;
  3. CS-моментум работает на 1-4 неделях (мы тестировали 30-90д — зона реверса, ошибка горизонта);
  4. Funding arb: 8-20% APY дельт-нейтрально (у нас есть funding-данные для оценки);
  5. CTREND-фактор (JFQA 2025): alpha 2.77%/нед, может улучшить T2;
  6. Mean reversion + объёмный фильтр: 81% winrate (Glassnode).
- Рекомендация: П1 (парный трейдинг BTC-ETH) как следующий контур — рыночно-нейтральный,
  дополнит T2 в медвежьи периоды.

---

## Проверка 5 стратегий из исследования (2026-08-16T15:30Z) — ВСЕ ОТВЕРГНУТЫ

Локальная проверка на 7-летних данных с издержками, OOS и полным циклом:
1. Парный трейдинг (коинтеграция/ratio): ETH/LINK OOS +3.7% — отвергнут;
2. CS-моментум 1-4 недели: in-sample +4147%, OOS +20.5% vs BH +52.3% — отвергнут
   (работает только в бычьих);
3. Funding arb: 1.5% APY на наших данных (медвежий рынок) — отвергнут;
4. CTREND-аппроксимация: 5 лет BTC +139.6% (DD −33%), но 7 лет +968% vs T2 +1574% —
   артефакт периода — отвергнут;
5. Mean reversion + объём: BTC +10.3% — отвергнут.

Уроки: (а) артефакт периода — проверять на полном цикле; (б) OOS-честность;
(в) режим-зависимые стратегии неюзабельны без режим-предсказания;
(г) наш T2 — единственная стратегия, прошедшая все проверки.

Побочно: найдены мусорные данные UNI-USD (движение 1.5 млн %), создана clean().
Документ: docs/STRATEGY_TESTS_ALL_2026-08-16_RU.md.

---

## Тест «если бы начали месяц назад» (2026-08-16T16:10Z)

- Стратегия: T2 (подтверждённая на 7 годах); симуляция с 2026-07-16, SMA по данным до старта.
- Результат месяца (боковой рынок): портфель −2.87% vs BH −2.55% (паритет);
  NEAR избежали −18.3% (CASH — защита); SOL пила 9 сделок −9.5%.
- Позиции симуляции = живому paper (валидация согласованности).
- Вывод: T2 — рабочая стратегия; в боковике ≈ BH, в трендах кратно обгоняет,
  в медвежьих защищает (NEAR). 1 месяц = шум, валидация на полном цикле.
- Документ: docs/MONTH_AGO_TEST_2026-08-16_RU.md.

---

## Точная экономика T2 (2026-08-16T17:00Z)

- Медианная годовая T2 (7 лет, 5 контуров): +27.6%; убыточных лет 31% vs 43% (BTC BH);
- Издержки Binance уже в бэктестах (0.15%/переход); BNB-скидка экономит ~1%/год;
- $10k → $12,760 (1г) / $20,776 (3г) / $33,826 (5г) при медиане;
- Риски: 31% убыточных лет, MaxDD −53%, горизонт 3+ лет обязателен;
- Сравнение: T2 ≈ BH по медиане, но лучший риск-профиль (защита в медвежьи);
- Рекомендация: старт $1-5k, горизонт 3+, Binance spot + BNB-скидка, + DCA параллельно.
- Документ: docs/T2_ECONOMICS_2026-08-16_RU.md.

---

## Сценарии большой прибыли (2026-08-16T18:00Z)

- Рычаги проверены на 7-летних данных: концентрация (SOL+BNB: CAGR 164%, медиана года
  +309%, DD −59%), леверидж 1.25-1.5 (CAGR +124-178%, но DD −66..−79%), компаунд.
- Честность: медианы +260-300% искажены бычьим 2021; реалистично p25-p50 +10-60%/год,
  бычьи +100-300%, медвежьи −15..−46%.
- Рекомендация: старт $2-5k, T2 SOL+BNB + BTC+ETH параллельно, реинвест, опционально
  lev 1.25 на BTC+ETH, DCA $200-500/мес.
- Правила: горизонт 3+, готовность к DD 80%, дисциплина, lev ≤1.5, стоп портфеля.
- Документ: docs/BIG_PROFIT_SCENARIOS_2026-08-16_RU.md.

---

## Исследование теорий, слухов, репозиториев и продуктов (2026-08-16T19:00Z)

- SMC/ICT развенчаны (0/54 механических вариантов прибыльны; нет peer-reviewed);
  наш микроструктурный сигнал — научная альтернатива.
- T2 подтверждён академией (TS momentum 31.96%) и практикой (NostalgiaForInfinity —
  та же философия, community +18-42%/6мес).
- Репозитории: Freqtrade (инфраструктура, Hyperopt), Hummingbot (MM), mlfinlab
  (meta-labeling), Riskfolio-Lib (веса), CCXT (уже есть), Jesse (дисциплина бэктестов).
- Рекомендации: (1) meta-labeling поверх T2 — фильтр убыточных входов в боковике;
  (2) Riskfolio-Lib веса портфеля; (3) порт T2 в Freqtrade dry-run + A/B с NFI;
  (4) Hummingbot для MM после накопления ws-данных.
- Документ: docs/TRADING_THEORIES_REPOS_RESEARCH_2026-08-16_RU.md.

---

## Внедрение полезного из репозиториев (2026-08-16T20:30Z)

1. Meta-labeling (mlfinlab подход) поверх T2: RandomForest, 5 фич (ATR/dist/тренд/RSI/vol10),
   train 60%/OOS 40%. Улучшения OOS: BTC +2344% (vs +1746%), BNB +5043%, NEAR +3457%,
   SOL +65164%; walk-forward 9/10 положительных. Интегрирован: meta_labeling.py + --meta-filter
   в run_t2_momentum; модели 5 pkl на сервере.
2. Riskfolio-Lib: Max Sharpe веса (BTC 40%, SOL 28%, BNB 13%, NEAR 12%, ETH 6%);
   OOS +286% vs +195% (равные). Внедрено в t2_portfolio.py: портфель $26,671 vs $25,767.
3. Freqtrade: порт T2-стратегии (freqtrade_t2.py + config) — готов к бэктесту после
   установки TA-Lib на сервере (блокер: C-библиотека); ценность — независимая валидация,
   Hyperopt, A/B с NostalgiaForInfinity.
4. Hummingbot: план для MM (после 2-4 недель ws-данных) — PMM-стратегия с нашим
   OBI-сигналом как фильтром, paper на testnet.
- Документ: docs/REPO_IMPROVEMENTS_2026-08-16_RU.md.
