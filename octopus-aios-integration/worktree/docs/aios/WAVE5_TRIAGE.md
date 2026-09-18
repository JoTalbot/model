# Wave 5 — Триаж (items 2,3,5,6,8b,15,19,20 + остатки волн 1–4)

Источник: `clean-code-production` ($B). Правило волны: файлы приезжают
paper/dry/disabled; юниты — только disabled; включения — отдельной командой.

## Среда приёмника (рекон 2026-09-08)

- В `/opt/aios-venv` НЕТ: nicegui, talib, torch, SB3, gymnasium, optuna,
  lightgbm, xgboost, arch, statsmodels, **ccxt**. ЕСТЬ: fastapi, uvicorn,
  starlette, websockets, httpx, requests, playwright. Python 3.12.3.
- Следствие: код с `import numpy/pandas/torch/ccxt/nicegui` на верхнем уровне —
  только код (reference), тесты к нему — с `pytest.importorskip` либо не портируем.
- Паттерн волны 4 (ленивый импорт тяжёлых lib внутри методов) применяем точечно:
  `data_collector` (ccxt), `collect_orderbook_snapshots` (ccxt).

## 5a — Доки (19) + дашборды (20)

- 19: из 193 волна 1 уже привезла 163 под другими именами: `instructions/`
  (байт-в-байт = `octopus_instructions/`, 102) + `coordination/` (61, идентично).
  В 5a добавляем только `octopus_projects/` (30; `projects/` волны 1 — другое
  содержимое, не трогаем). Переименований ради канона не делаем.
- 20: `web_gui/` НЕ СУЩЕСТВУЕТ ни на одной ветке (0 файлов) — в манифесте ошибка.
  Фактический состав (22): `aios_core/{dashboard,ai_safety_dashboard,
  operator_dashboard_api,dashboard_websocket_test}.py` + `dashboard_views/` (13)
  + `run_dashboard{,_nicegui,_unified}.py` + `dashboard_v2.py`, `dashboard_v3.py`
  (найдены через юниты) + `seed_dashboard_data.py` (support).
- Рабочие: `operator_dashboard_api` (fastapi-мост, 28 строк), `ai_safety_dashboard`
  (stdlib), `dashboard_websocket_test` (uvicorn+requests клиент), `seed_*` (stdlib).
  Остальное — reference: `dashboard.py` тянет непортируемые соседние модули
  (`android_auto_study`, `backup_manager`, `orchestrator`), views/v2/v3 — nicegui,
  раннеры ссылаются на несуществующие `container`/`web_gui` (битые ссылки апстрима).
- Юниты: `octopus-dashboard-v2/v3` (disabled). Остальное без юнитов.

## 5b — Freqtrade T2 (2) + остатки T2

- Порт: `scripts/{freqtrade_t2,freqtrade_t2_hyper,freqtrade_config_t2.json,
  run_t2_executor,run_t2_momentum,t2_portfolio}.py` → `scripts/aios/freqtrade/`.
- `run_t2_executor`/`run_t2_momentum`/`t2_portfolio` — stdlib, рабочие.
  Канон paper-loop — `scripts/run_t2_momentum.py` (311 строк, с meta-фильтром);
  дубль `tests/run_t2_momentum.py` (287 строк) НЕ портируем.
- `t2_validation`/`quant_t2_metrics`/`test_t2_paper`/`meta_labeling` — numpy:
  только код; тесты `test_t2_metrics`/`test_t2_paper` — с `importorskip("numpy")`.
  `scripts/test_t2_paper.py` (PASS/FAIL-скрипт) — только код, не тест CI.
- Стратегия/гипер — только код (нужен freqtrade-venv, которого нет; venv
  в волне не создаём). Юниты: `octopus-freqtrade-t2-dry`, `octopus-t2-momentum`
  (disabled). `freqtrade_config_t2.json`: dry_run=true как есть.

## 5c — Коллекторы и сигналы (3)

- Рабочие (stdlib): `collect_{derivatives,funding_oi,market_context,news_sentiment}
  _daily`, `prune_orderbook_ws`, `mm_queue_priority` + support `mm_queue_model`,
  `orderbook_analyzer`, `crypto_news_sentiment`, `derivatives_orderbook_engine`.
- `collect_orderbook_ws` — websockets ✅ рабочий.
- Ленивый ccxt: `aios_core/quant/data_collector.py` → `swarm/quant/` (остаток
  волны 4), `collect_orderbook_snapshots` — модуль импортируется, live-fetch
  падает с понятной ошибкой. Тест `test_quant_backfill_pagination` — рабочий.
- numpy (только код): `mm_hourly_features`, `mm_signal_emitter`,
  `mm_signal_live_monitor`, `score_historical_sentiment` (проверить при стейджинге).
- Дайджест-мост: `run_market_data_collector.py` → импорт из `swarm.quant`.
- Сигналы: отдельного `swarm/quant/signals.py` НЕТ (в триаже была ошибка) —
  сигнальная логика волны 4 живёт в `ml_signal_bridge`/`rl_signal_bridge`/
  `quant_trading_engine`; новых файлов не требуется. `run_market_digest.py`
  перенесён из 5f в 5c (рыночный дайджест, stdlib, к нему юнит market-digest).
- Юниты (disabled): derivatives, market-context, market-data, market-digest,
  mm-* (4), news-scoring, news-sentiment, orderbook-research, orderbook-ws,
  orderbook-ws-prune.

## 5d — ML/RL (5) + остатки исследований

- `scripts/quant_ml*` (9) + `quant_train_ppo*` (2) + `run_quant_ml_inference` +
  `gen_quant_notebooks` + `colab_automation_runner` — только код (numpy/pandas/torch).
- Ноутбуки: `docs/AIOS_Colab_Quant_{Clustering,ML_Training,RL_Training}.ipynb`
  → `docs/aios/notebooks/`. Остальные 6 ipynb — вне скоупа (не quant).
- Исследовательский зоопарк (stdlib, РАБОЧИЙ + тесты): `run_quant_{arbitrage_oos,
  cross_sectional,low_frequency_trend,pairs_oos,regime_v3,walkforward_v2}`,
  `quant_strategy_scoreboard`, `check_quant_v2_gate`, `compare_quant_research`,
  `generate_quant_signal_product` + support `aios_core/quant_regime_v3.py` →
  `swarm/quant/`. Тесты: все `test_quant_*` из списка (кроме signal_api —
  тянет `api/monetization_routes`, вне скоупа → DEFER).
- `quant_strategy_robust` — numpy → только код, без теста.
- `backtest_ai_strategies` (stdlib, остаток волны 4) → `swarm/quant/`, без теста.
  `ml_predictor` (pandas) → только код. `ab_report/ab_verdict` тесты → ПЕРЕЕЗД
  `quant_ab_report` из `swarm/tgbot/support/` в `swarm/quant/` (правильный дом;
  `quant_cmds` обновить, шим не оставлять).
- Юниты (disabled): quant-ml-inference/monitor/retrain, quant-signal-product,
  quant-ab-report, colab-quant-ml. `quant-trading(-control)` → НЕ портируем
  (live-торговля, вне скоупа).

## 5e — DeFi (6), только код

- Состав манифеста УСТАРЕЛ (файлов `scripts/{arbitrage_detector,...}` нет на $B).
  Факт: `aios_core/{defi_yield,live_onchain_listener,onchain_splitter,
  dex_arbitrage_scanner,triangular_arbitrage}.py`, `run_{live_onchain_listener,
  yield_sweeper,dex_arbitrage_scanner}.py`, `scripts/check_defi_yield_gate.py`,
  тест `test_defi_yield_gate` + `aios_core/quant/uniswap_v3.py` (остаток волны 4).
- Рабочие: `defi_yield` + `check_defi_yield_gate` + тест (stdlib),
  `triangular_arbitrage` (stdlib), `uniswap_v3` (urllib/DefiLlama, DATA-мост).
- Только код (web3/`crypto_wallet`/`kraken_client` вне скоупа): сканеры, слушатель,
  сплиттер, свипер.
- Юниты: `octopus-yield-sweeper`, `octopus-live-onchain-listener`,
  `octopus-defi-risk-monitor` (disabled). Отдельного `defi-gate` юнита нет —
  его роль играет `defi-risk-monitor` (check через bash-обёртку).

## 5f — Маркетплейсы (15) + OLX-раннеры

- `aios_core/modules/`: 93 файла, из них whatsapp+viber (14) НЕ портируем
  (мессенджеры, тянут цепочку `platforms/{doctor,hintmsg,recipe,secrets,
  runtime_hints}` вне скоупа). Порт: 79 файлов (8 dirs: bigl, facebook,
  instagram, olx, prom, rozetka, shafa, tiktok) → `swarm/marketplaces/`.
  Модули self-contained (только stdlib + внутренние относительные импорты,
  playwright/bs4/httpx внутри НЕТ).
- Раннеры: `run_olx_autoreply` (393, stdlib), `run_olx_chat_alerts`,
  `run_olx_http_collector`, `run_olx_pipeline`, `run_olx_price_alerts`,
  `run_market_digest` (stdlib), `run_weekly_digest` (проверить), `run_digest`
  (проверить; юнит `aios-digest`).
- `aios-olx-autoreply` юнит → DEFER: `run_autonomy_cli.py olx --loop` требует
  `aios_core/autonomy/` (14 файлов, ~2800 строк, вне выбранных пунктов).
  Сам `run_olx_autoreply.py` портируем (тело цикла на месте).
- Юниты (disabled): olx-chat-alert/collector/pipeline/price, market-digest,
  weekly-digest, digest. Без юнита: autoreply (defer, см. выше).

## 5g — Balancer-слияние (8b)

- По spec из волны 1: `aios_core/llm_balancer.py` + `tools/llm_balancer.py` →
  слияние в `swarm/llm/` (`key_pool.py`, `router.py` уже есть), убрать
  `sys.path /opt/aios` из прод-бота, тесты балансера.

## Отложено за пределы волны 5 (не забыть)

- Включение юнитов (все disabled) — отдельной командой на каждый.
- `test_quant_signal_api` (нужен `api/monetization_routes`), skill-тесты (82).
- Ключи Kraken в истории AIOS — ротировать (напоминание из волны 4).
- freqtrade-venv / quant-venv / обучение ML — вне прод-сервера.
