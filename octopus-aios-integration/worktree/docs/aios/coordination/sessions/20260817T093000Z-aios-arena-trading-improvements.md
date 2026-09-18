---
session_id: "20260817T093000Z-aios-arena-trading-improvements"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T09:30:00Z"
updated_utc: "2026-08-17T11:20:00Z"
branch: "agent/20260817-trading-improvements"
base_commit: "ab7e70ec"
claim: "coordination/claims/trading-improvements--20260817T093000Z-aios-arena-trading-improvements.md (снят при завершении)"
---

## Цель

Реализовать улучшения трейдинга, утверждённые владельцем 2026-08-17 (пункты 1-7):
latency_ms, MemoryMax+swap, калибровка в ретрайн, свежесть калибровки в мониторе,
100мс-стрим BTC/ETH, A/B-отчёт, алерт застоя.

## Итоговое состояние

1. latency_ms: измеряется из aggTrade E (avg ~205ms; max до 3.7s на реконнектах). ✓
2. MemoryMax: market-data 2G, orderbook-ws/freqtrade 1.5G, quant main/control/ml-inference 1G;
   swap +4G (swapfile2, fstab) → 8G. ✓
3. Ретрайн: деплой кандидата только с sane q90 (band 0.40-0.90) от его test-window
   распределения; калибровка пишется атомарно вместе с моделью. ✓
4. Монитор: свежесть калибровки (model mtime vs calibration) + застой A/B (>3дн, 0 входов).
   Health check поверхностно шлёт quant-проблемы в TG. ✓
5. 100мс-стрим BTC/ETH: full-режим (~8.6 сэмпл/с каждая), retention 7д держит бюджет. ✓
6. A/B-отчёт: scripts/quant_ab_report.py + aios-quant-ab-report.timer (Sun 16:30Z). ✓
7. Алерт застоя: в мониторе (hourly) + health check (daily TG). ✓

Бонус-наблюдение: после калибровки гейта (0.5061) Directional v2 paper дал первые
входы — 1 сделка в каждом контуре (kraken, net −2.06 USD на $10k, fees+exec −1.0,
max DD 0.021%). A/B-эксперимент накапливает статистику.

## Проверки

- [PASS] py_compile всех изменённых файлов.
- [PASS] целевые тесты: ws 3/3, ab 2/2, policy, prune, systemd inventory, budget, inventory.
- [PASS] audit_deployment_sources.py --runtime --strict (drift 0).
- [PASS] калибровка перегенерирована: q90=0.5061 (n=287066).
- [PASS] полный pytest: только 3 преэкзистинг-провала чужих областей
  (tests/macro test_hourly_normalization gran, test_v22_api monetization routes,
  ERROR tests/macro test_feature) — не от правок этой сессии.
- [PASS] A/B-отчёт: первый прогон сформирован (data/reports/quant_ab_report.json).
- [PASS] таймер ab-report active; swap 8G; все 7 трейдинг-сервисов active.

## Git

- Коммиты (ветка agent/20260817-trading-improvements, не опубликована):
  944c8e5b, 625d9432, 72575d06, 1f323c36, fba876d3.
- Чужие изменения не затронуты (catboost_info, run_hyperopt_guarded.sh, skills/*).

## Handoff

- Следующий шаг: наблюдать за входами Directional v2 и еженедельным A/B-отчётом;
  через 2-4 недели MM-вердикт на ws-данных (теперь с latency и 100мс-стримом).
- Блокеры: нет.
- Риски: полный стрим BTC/ETH удваивает приток строк (~0.7G/день); retention
  держит steady-state; следить за диском (сейчас 54%).
- Что нельзя делать без повторной проверки: live, изменение порогов, отключение retention.
