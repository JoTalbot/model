---
session_id: "20260817T190000Z-aios-arena-month-strategy-test"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T19:00:00Z"
updated_utc: "2026-08-17T19:50:00Z"
branch: "agent/20260817-month-strategy-test"
base_commit: "c594d81c"
claim: "coordination/claims/month-strategy-test--20260817T190000Z-aios-arena.md (снят при завершении)"
---

## Цель

Бэктест стратегий «как будто торги стартовали 1 месяц назад», определить победителя.

## Итог

Окно 2026-07-17 → 2026-08-17 (медвежий месяц: средняя по 32 монетам −7.59%):
- M2 CS-момент топ-5 (30д): +1.9% (DD −5.9%) — ФОРМАЛЬНЫЙ победитель, но OOS −46%/2г.
- M1 +1.0%, M3 +1.1%; DCA топ-10 +1.12%; B&H корзины +1.43%; BTC +0.74%.
- T1/T4/C1 flat; T3 −1.0%; freqtrade T2 портфель −1.19%; T2 SMA50 −4.1%.
- Directional v2 (развёрнутый гейт 0.5061): −0.38% (9 сделок, win 55.6%) при
  рынке −7.59% → +7.2 п.п. к рынку, лучший среди активных по сохранению капитала.
- Free-profile контроль: −31.34% (269 сделок) — подтверждает цену издержек.
- Устойчивый выбор по совокупности: пассивная корзина топ-10 мейджоров.

## Изменённые файлы

- scripts/quant_monthly_backtest.py — +--ml-min-prob, +--trail-ratio (обратно совместимо).
- scripts/momentum_strategies.py — +--eval-last-days N (оценка «старт N дней назад»).
- docs/STRATEGY_MONTH_BACKTEST_2026-08-17_RU.md — сводный отчёт.
- data/reports/monthly_1m_* (4 сценария), momentum_strategies_month.md — артефакты (untracked runtime).

## Проверки

- [PASS] pytest test_quant_monthly_backtest + test_momentum + test_policy_compare.
- [PASS] все прогоны завершились rc=0; отчёты прочитаны.

## Git

- Коммит: 0243e9af (ветка agent/20260817-month-strategy-test).

## Handoff

- Следующий шаг: решение владельца — оставить текущий набор (Directional v2 + DCA)
  или добавить M2-вариант в paper-контур (не рекомендуется: OOS −46%).
