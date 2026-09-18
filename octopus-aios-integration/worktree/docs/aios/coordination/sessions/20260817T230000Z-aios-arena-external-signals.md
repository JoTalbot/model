---
session_id: "20260817T230000Z-aios-arena-external-signals"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T23:00:00Z"
updated_utc: "2026-08-17T23:00:00Z"
branch: "main"
base_commit: "d8ae1f8f"
claim: "coordination/claims/external-signals--20260817T230000Z-aios-arena.md (снят при завершении)"
---

## Цель

Внешние данные для сигнала (последнее непроверенное направление Edge Lab).
Уже закрыто: macro/on-chain/derivatives (~0 corr), funding (отрицательный),
news (отрицательный), ML-CS, MTF, tf×universe. Непроверено: (1) кросс-активные
lead-lag (BTC/ETH → альты на 1h, год истории — тестируется сразу); (2)
1h-агрегированная микроструктура из ws-стрима (данных пока ~40ч — пайплайн +
weekly-таймер, предварительный статус).

## Scope

- scripts/quant_lead_lag.py (новый), scripts/mm_hourly_features.py (новый),
  tests/*, deploy/systemd/aios-mm-hourly-features.* (новые), docs/*, coordination/*.
- Вне scope: прод-торговый код; чужие изменения.


## Итог (дополнение)

1. Lead-lag ОТКЛОНЁН: lag1 corr 0.001 vs lag0 0.654 — рынок синхронный на 1h;
   правило BTC-моментума: 0/31 альтов положительны net of cost.
2. Микроструктурный пайплайн: mm_hourly_features.py + weekly-таймер;
   1181 symbol-hours; предварительные корреляции ≈ 0 (диапазон −0.028…+0.024).
3. Отчёт docs/EXTERNAL_SIGNALS_2026-08-17_RU.md; тесты lead-lag 3/3, hourly 4/4.
4. Коммит f74567fb, ветка agent/20260817-external-signals.

## Проверки

- [PASS] pytest тесты lead-lag/hourly/systemd inventory/project inventory.
- [PASS] audit_deployment_sources --strict: 0 drift.
