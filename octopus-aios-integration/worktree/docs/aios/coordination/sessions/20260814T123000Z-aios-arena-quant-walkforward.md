# Сессия: cost-aware walk-forward backtest

---
session_id: "20260814T123000Z-aios-arena-quant-walkforward"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T12:30:00Z"
updated_utc: "2026-08-14T12:55:00Z"
branch: "agent/20260814-quant-walkforward → main"
base_commit: "356ad7d1"
claim: "none (closed after artifact/gate verification)"
---

## Реализовано

Offline `scripts/run_quant_walkforward_v2.py`: закрытые 1h OHLCV, 70% train parameter selection, 30% untouched OOS, fees+spread+slippage 0.50% round-trip. Gate теперь использует `backtest_directional_v2.json`.

## OOS результат

- 35 активов; 12 положительных (34.3%).
- Average −0.354%; median −0.248%.
- 115 closes; 29 wins; win-rate 25.2%.
- Aggregate profit factor 0.374.
- Best WIF/Kraken +0.510%; worst UNI/Kraken −1.608%.

## Проверки

- 4 generator/gate tests.
- Полный suite: 5 198 = 5 191 passed, 7 skipped, 0 failed.
- Artifact: `data/reports/backtest_directional_v2.json`.
- Gate `ready=false`; entry mode freeze не изменён.

## Git

- Implementation commit: `276950cd`.

## Handoff

Directional v2 не имеет OOS edge после costs. Нельзя enable/live. Следующая стратегия получает новый untouched OOS window; текущий test-сегмент нельзя использовать для подбора.
