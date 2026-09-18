---
session_id: "20260817T153000Z-aios-arena-bnb-maker-rebate"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T15:30:00Z"
updated_utc: "2026-08-17T16:05:00Z"
branch: "agent/20260817-trading-improvements"
base_commit: "bd80f7be"
claim: "coordination/claims/bnb-maker-rebate--20260817T153000Z-aios-arena.md (снят при завершении)"
---

## Цель

Проверка maker-rebate гипотезы для BNB: сетка комиссий на gated/naive MM,
точка безубыточности, сравнение с ландшафтом площадок.

## Итог

- BNB gated: breakeven fee = −0.0127%/сторону (нужен ребейт ≥1.3bps) — лучший
  кандидат выборки (BTC gated −0.0256%, naive хуже).
- При 0% комиссии BNB gated всё равно отрицателен (−11.92): adverse selection
  (−6.96) + inventory MTM (−4.96); ребейт должен покрывать оба канала.
- Ландшафт 08.2026: Binance spot 0.075% (с BNB), futures maker 0.02% (заряд);
  OKX spot 0.08%; ребейты только VIP7+ (недостижимо).
- Вердикт: ОТКЛОНЕНА при доступных условиях; BNB остаётся первым кандидатом,
  если появится ребейт-площадка; масштаб при 2bps ребейте +6.9 USD/40ч — незначим.

## Изменённые файлы

- scripts/mm_maker_fee_sensitivity.py — новый (сетка комиссий, breakeven-интерполяция).
- tests/test_mm_maker_fee_sensitivity.py — 4 теста.
- docs/MM_BNB_MAKER_REBATE_2026-08-17_RU.md — отчёт.
- coordination/* — журнал, claim, PROJECT_CONTEXT.

## Проверки

- [PASS] pytest tests/test_mm_maker_fee_sensitivity.py 4/4.
- [PASS] прогон: 2 пары × 2 режима × 9 комиссий завершён, отчёт записан.

## Git

- Коммит: c15fb01b (запушен с веткой).

## Handoff

- Следующий шаг: наблюдение за A/B Directional v2; MM закрыт до появления ребейт-условий.
