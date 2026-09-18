# Wave 4 — triage (item 1, quant paper engine)

Порт бумажного quant-движка: `swarm/quant/` (15 модулей), раннер
`scripts/aios/run_quant_trading.py`, 2 юнита-daemon'а (files-only, disabled),
10 тестов. Продовая venv не содержит numpy/pandas/web3/ccxt/torch — движок
портирован в stdlib-first: тяжёлые зависимости опциональны, paper-цикл
работает без них (доказано смоуком импорта с заблокированными пакетами, 15/15).

## 1. Манифест `swarm/quant/`

| Модуль | Строк | Назначение |
|---|---|---|
| quant_trading_engine | ~1780 | движок: MarketDataFeed, QuantSignalEngine, PaperTradingSimulator, QuantMasterOrchestrator (legacy, opt-in), MultiExchangeQuantEngine (Directional v2), отчёты |
| quant_directional_policy | ~170 | fail-closed риск-политика входов (конфиг из env) |
| quant_directional_v2 | ~380 | изолированное paper-исполнение multi-exchange цикла |
| quant_regime_v3 | ~110 | вычисление режимных фич |
| quant_report_formatters | ~300 | чистые форматтеры отчётов (без операционных импортов — проверено тестом) |
| swarm_quant_backtester | ~120 | SMA-бэктест + ройный консенсус |
| kraken_client | ~120 | REST-клиент Kraken (публичные тикеры + опциональные приватные вызовы) |
| crypto_wallet | ~575 | EVM-кошелёк/утилиты (web3 опционален) |
| llm_swarm_debate | ~90 | дебаты роя (litellm/chromadb опциональны, балансировщик — octopus) |
| ml_gate_calibration | ~60 | q90-порог ML-гейта (numpy → stdlib, бит-в-бит) |
| ml_signal_bridge | ~100 | read-only доступ к ml_signals.json (graceful при отсутствии) |
| rl_signal_bridge | ~280 | PPO-инференс (torch опционален, модель-файл опционален) |
| market_regime | ~160 | чистые функции классификации режима + write_latest/append_history |
| regime_guard | ~30 | kill-guard CRASH/PANIC, fail-open |
| paths (NEW) | ~20 | `resolve_data_dir()`: явный путь или `$OCTOPUS_DATA_DIR` |

## 2. Безопасность: секреты Kraken и paper-only

1. **В апстриме захардкожена ЖИВАЯ связка `api_key` + `api_secret`** (`kraken_client.py`,
   метод `add_market_order` → реальный `AddOrder`). В порт НЕ вошли: ключи читаются
   из `OCTOPUS_KRAKEN_API_KEY`/`OCTOPUS_KRAKEN_API_SECRET` (дефолт — пусто).
   ⚠️ Ключи лежат в истории git AIOS — **рекомендуется отозвать их на Kraken**.
2. `add_market_order` в порту запрещён без `OCTOPUS_KRAKEN_LIVE=1` (возвращает
   `{"status": "error", ...}`, приватный вызов не выполняется). Покрыто тестами
   (запрет по дефолту + opt-in с моком `_query`).
3. Paper-цикл (`run_cycle` → `run_multi_exchange_cycle`) ордеров не создаёт:
   в коде AIOS `add_market_order` вызывают только `run_kraken_manager.py` (ручной CLI)
   и `tg_bot/treasury.py` (item 17, не выбран, не портируется). Движок использует
   kraken-клиент только для публичных тикеров.
4. Дополнительно исправлен B006 (`data: dict = {}` → `None` + копия): оригинал
   мутировал словарь вызывающего (дописывал nonce). Поведение вызовов сохранено.

## 3. Адаптации путей и env

- `data_dir="/root/AIOS/data"` (10 сайтов) + docker-sniff блоки
  (`/.dockerenv`, `/proc/self/cgroup`, `/app/data`) → `None` + `resolve_data_dir()`.
  Функции-сквозняки (`get_multi_exchange_demo_report` и др.) пробрасывают `None`
  до листьев, где он резолвится.
- `AIOS_QUANT_*` → `OCTOPUS_QUANT_*` (21 переменная: код + тесты + юниты, без фолбэка).
- Относительные дефолты `data/quant/ml_prob_calibration.json`,
  `data/reports/market_regime_latest.json` во `from_env` → абсолютные через живой
  `$OCTOPUS_DATA_DIR` (CWD-независимость; статические дефолты датакласса оставлены
  как в апстриме — `from_env` их перекрывает).
- Мосты: `REPO_ROOT=parents[2]` → `$OCTOPUS_DATA_DIR` (`quant/ml_signals.json`,
  `quant/models/ppo_v9.pt`, `quant/rl_signals.json`); `.env` → `$OCTOPUS_ENV_FILE`;
  логгеры `AIOS.*` → `Octopus.*`; User-Agent'ы → `Octopus-*`.
- Раннер: `sys.path` → `$OCTOPUS_ROOT`; импорт движка с `# noqa: E402`.
- Проверка: `grep -rn "/root/AIOS|/opt/aios|/etc/aios|dockerenv|/app/data"` — 0 в коде.

## 4. Опциональные зависимости (все guarded)

| Зависимость | Где | Решение |
|---|---|---|
| web3 | crypto_wallet (top-level) | try/except на импорте; `check_*` возвращают error-dict, `send_*` — error-dict; конструктор и vault/ledger работают без web3 |
| numpy | ml_gate_calibration (top-level) | stdlib `_quantile` (линейная интерполяция) — дифф-тест против numpy: 300 случайных распределений, совпадение бит-в-бит |
| ccxt | engine (lazy, batch-тикеры 5 бирж) | уже lazy; без ccxt ветка падает внутрь окружающего try (квирки бирж опциональны) — поведение апстрима |
| torch/numpy | rl_signal_bridge (lazy) | уже guarded (`_model_available`, try/except); без модели/ torch — пустые сигналы |
| matplotlib/openpyxl | engine (chart/xlsx экспорт) | уже lazy; вызываются только из отчётных функций, не из paper-цикла |
| litellm/chromadb | llm_swarm_debate | уже guarded; убран шумный `print` при отсутствии chromadb (тихий import) |
| pandas | — | в портируемом сете не используется (только в отложенном ml_predictor) |

## 5. Внутренние импорты: переписанное и отложенное

- `aios_core.quant.*` → `swarm.quant.*`, `aios_core.quant_*` → `swarm.quant.quant_*`,
  `kraken_client`/`crypto_wallet`/`llm_swarm_debate` → `swarm.quant.*`.
- `tg_bot.credentials` → `swarm.tgbot.credentials` (экспорты проверены);
  `aios_core.llm_balancer` → `swarm.tgbot.support.llm_balancer` (до слияния в Wave 5).
- Отсутствующие модули (guarded try/except в апстриме) → зарезервированные пути
  `swarm.quant.signals.*`: `orderbook_analyzer`, `crypto_news_sentiment`,
  `defi_yield`, `dex_arbitrage_scanner`, `gas_sentry`. ImportError ловится гардами —
  деградация graceful, как задумано.
- Два НЕguarded сайта (`analyze_single_asset_360`, частично) обёрнуты в try/except
  с дефолтами (`orderbook: unavailable`, `sentiment: UNKNOWN`) — иначе падение по
  отсутствующим wave-5 модулям. `get_ai_portfolio_advice` не тронут (балансировщик
  существует). Обе функции вне paper-цикла.
- Совместимость: `test_legacy_module_reexports_exact_formatter_objects` требует
  `engine.format_*` — реэкспорт восстановлен с `# noqa: F401` после того, как
  `ruff --fix` удалил его как «неиспользуемый». Остальное, удалённое фиксом как
  мёртвое (`PUBLIC_RPC_NODES` в engine), тестами не используется — проверено.

## 6. Отложено в Wave 5

- `quant/uniswap_v3.py` (item 6, DeFi); `quant/data_collector.py` (item 3, нужен ccxt);
  `quant/ml_predictor.py` (item 5, нужен pandas); `quant/backtest_ai_strategies.py`
  (item 5, research). Движок их не импортирует — проверено.
- `tests/test_quant_regime_v3.py` (импортирует `scripts/run_quant_regime_v3.py` —
  wave-5 скрипт); `test_market_universe_uses_current_asset_symbols` из v2-теста
  (проверяет `data_collector.DEFAULT_SYMBOLS` — уедет вместе с ним).
- Юниты quant-ml-*/quant-signal-product/quant-ab-report (ML-инференс и продукты —
  items 3,5).
- Писатели `quant/orderbooks.sqlite`, `quant/news_sentiment.jsonl`,
  `t2_*_equity.jsonl`, `reports/{basket_paper,strategy_scoreboard}.*` — items 2,3,5.

## 7. Контракты данных (что движок пишет/читает)

Пишет в `$OCTOPUS_DATA_DIR`: `multi_exchange_portfolios{_v2,}.json` (имя выбирается:
параметр → env → `_v2` если есть → legacy), `paper_portfolio.json`,
`kraken_paper_portfolio.json`, `price_history_quant.json`, `.wallet_vault.json`,
`self_funding_ledger.json`. Юниты задают `multi_exchange_portfolios_owner_paper{,_control}.json` —
ровно то, что читают `/digest` и `/ab` Волны 3.
Читает (все отсутствия — graceful): `quant/ml_signals.json`,
`quant/models/ppo_v9.pt`, `quant/ml_prob_calibration.json`,
`reports/market_regime_latest.json` (пишется `scripts/quant_regime_engine.py`, wave 5).

## 8. Юниты (files-only, disabled)

`octopus-quant-trading.service` + `octopus-quant-trading-control.service`
(`Type=simple`, `--daemon --interval 900`, `Restart=always`, `MemoryMax=1024M`,
21 `OCTOPUS_QUANT_*`, трейл 1.0 vs 0.988). НЕ enable'ить до Wave 5: без
ML-сигналов (`REQUIRE_ML=1`, файлов нет) входы закрыты политикой (fail-closed) —
демон будет крутиться вхолостую; плюс нет `market_regime_latest.json`.

## 9. Тесты и CI

- Портировано 9: policy, directional_v2 (минус 1 тест свежести тикеров),
  report_formatters, run_quant_trading_v2, trading_accounting, trading_fees_risk,
  trade_introspection, market_regime, tg_quant_cmds (ROOT→DATA, `reports/` прямо
  в tmp). Все офлайн (tmp_path, моки fetch), CWD-независимы.
- NEW `tests/test_quant_port.py` (12 тестов): kraken-гварды, немутация словаря,
  `resolve_data_dir`, офлайн-конструкция движка + paper-сигнал (socket-block),
  `from_env`, квантили (фикс. значения), калибровка, regime-guard, web3-гварды
  (skip если web3 стоит).
- CI: `swarm/quant/` + 10 тестов в ruff/pytest списки `test.yml`/`security.yml`;
  `swarm/quant/` в arch-check `production-gate.yml`.
- Ruff проектным конфигом — 0 (было 125: 113+ автофикс, остальное вручную:
  перенос импортов наверх, SIM105, RUF059, E402-noqa, реэкспорт-noqa).
