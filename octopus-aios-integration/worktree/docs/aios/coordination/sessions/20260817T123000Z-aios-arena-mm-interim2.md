---
session_id: "20260817T123000Z-aios-arena-mm-interim2"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T12:30:00Z"
updated_utc: "2026-08-17T13:15:00Z"
branch: "agent/20260817-trading-improvements"
base_commit: "16f538b6"
claim: "coordination/claims/mm-interim2--20260817T123000Z-aios-arena.md (снят при завершении)"
---

## Цель

Промежуточный MM-анализ на накопленных ws-данных: сигнал, latency, gated vs naive.

## Итог

1. Сигнал 30s у мажоров СХЛОПНУЛСЯ с ростом выборки: BTC 0.867→0.578 (n 1247→24783),
   ETH 0.795→0.556 (n 2294→29451). Малокапы держат AUC 0.86-0.97, но n мал.
   Новое: BTC long-horizon (180-900s) AUC 0.63-0.66.
2. Naive MM на ws (40ч, 8 пар, queue-model): убыточен везде; gross<0 при нулевой
   комиссии (adverse selection −0.14…−0.73 $/fill при 2bps half-spread).
3. Gated: сокращает убыток 51-81%, знак не переворачивает (как 16.08).
4. Latency: транспорт 129-132мс медиана у всех 19 пар; post-split p90 BTC 245мс /
   ETH 355мс; хвосты редких пар — артефакт агрегации aggTrade на стороне Binance.

## Изменённые файлы

- scripts/mm_ws_backtest.py — новый драйвер (naive/gated + queue-model на snapshots_ws, децимация full-стрима).
- tests/test_mm_ws_backtest.py — 4 теста чистых функций.
- docs/MM_INTERIM_2026-08-17_RU.md — отчёт.
- coordination/* — журнал, claim, PROJECT_CONTEXT.

## Проверки

- [PASS] py_compile драйвера; pytest tests/test_mm_ws_backtest.py 4/4.
- [PASS] прогоны: naive 8 пар, gated 6 пар, horizons 19 пар (все завершились).
- [PASS] latency-статистика из БД по 19 парам.

## Git

- Коммит: 843d9f6e.

## Handoff

- Следующий шаг: ждать полных 2-4 недель 1Гц; модель очереди (калибр доли уровня);
  maker-rebate площадки только при устойчиво положительном gross.
- Риски: BTC long-horizon сигнал не исследован на OOS — не использовать без проверки.
