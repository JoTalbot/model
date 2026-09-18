---
session_id: "20260819T020000Z-aios-arena-regime-engine"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-19T02:00:00Z"
updated_utc: "2026-08-19T02:40:00Z"
branch: "agent/20260819-regime-engine"
base_commit: "f9cc9a1a"
claim: "coordination/claims/regime-engine--20260819T020000Z-aios-arena.md (снят при завершении)"
---

## Цель

Применить полезные рекомендации внешних ИИ (недвижимость исключена владельцем):
режимный движок + risk-guard + роутер стратегий + честные T2-метрики +
проверка стопов freqtrade + структура AI-аналитика.

## Итог

1. **Freqtrade stoploss-ловушка исправлена:** стратегия имела stoploss = -0.99
   (freqtrade читает как −99% → стоп = 1% от цены входа: BTC 645.41 при входе
   64540.94). Причина — намерение «без жёсткого стопа» (SMA-выход как защита),
   реализованное опасным значением. Заменено на страховочный −15%; бот
   пересчитал открытые сделки (BTC stop 54859.8, SOL 65.53). Тест-регрессия
   запрещает значения вне (−0.5, 0).
2. **Market Regime Engine:** aios_core/quant/market_regime.py — 7 режимов
   (STRONG_BULL/BULL/SIDEWAYS/VOLATILE/BEAR/CRASH/PANIC) из совокупности
   индикаторов (SMA200/50, ret7d, dd90, vol30, breadth, F&G); риск-уровни;
   роутер семейств стратегий; триггеры смены режима. scripts/quant_regime_engine.py
   — ежедневный сбор из локальных данных → market_regime_latest.json + история
   jsonl. Таймер 04:50 UTC. Текущий режим: BEAR (risk HIGH, defensive; dd90 −16.3%).
3. **Kill-guard политики:** regime_guard в DirectionalV2Config (env
   AIOS_QUANT_REGIME_GUARD); в CRASH/PANIC входы блокируются
   (regime_crash_kill), fail-open при отсутствии файла. Включён в обоих
   paper-демонах (unit env). Тесты: 5 случаев.
4. **T2-метрики:** scripts/quant_t2_metrics.py — PF/win-rate/expectancy по
   сделкам + Sharpe/Sortino/MaxDD/CAGR/Calmar по дневной истории, с честной
   пометкой «симуляция, не заработок». Отчёт data/reports/t2_simulation_metrics.md.
5. **AI-аналитик:** отчёт получил блок «🎛 Режим рынка и защита» (режим, риск,
   семейство стратегий, триггеры, CRASH/PANIC-блокировка); LLM-промпт требует
   вероятностные сценарии (без «точно»), раздел «Насколько можно доверять»
   (уверенность + качество данных).
6. **Бюджет модулей:** tg_bot/accounts.py вынесен seam pre_treasury_intents.py
   (перехват «Трейдинг» + «фриланс» до treasury) — accounts.py 3222/3225,
   policy 170/170.

## Изменённые файлы

- новые: aios_core/quant/{market_regime,regime_guard}.py,
  scripts/{quant_regime_engine,quant_t2_metrics}.py,
  tg_bot/pre_treasury_intents.py, deploy/systemd/aios-regime-engine.{service,timer},
  tests/{test_market_regime,test_regime_guard_policy,test_t2_metrics,test_freqtrade_stoploss}.py.
- правки: scripts/freqtrade_t2.py, aios_core/quant_directional_policy.py,
  tg_bot/{trading_report,accounts}.py, deploy/systemd/aios-quant-trading*.service,
  HETZNER_INSTALLED_UNITS.txt (176), tests/test_systemd_inventory.py,
  tests/test_trading_button_path.py, docs/PROJECT_INVENTORY.md.

## Проверки

- [PASS] тесты: regime 13/13, guard-policy 5/5, t2_metrics 5/5, stoploss 2/2,
  trading_report 13/13, budget, inventory.
- [PASS] живой прогон режимного движка; freqtrade пересчитал стопы.
- [PASS] полный pytest: единственный провал — stale inventory (перегенерирован).

## Git

- Коммит: 3f687afe (ветка agent/20260819-regime-engine).

## Handoff

- Следующий шаг: полный pytest → PR → мерж; наблюдение за режимом и guard.
- Риски: guard fail-open при отсутствии файла режима (задокументировано).
