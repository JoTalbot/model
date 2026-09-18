---
session_id: "20260817T235000Z-aios-arena-basket-variants"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T23:50:00Z"
updated_utc: "2026-08-17T23:50:00Z"
branch: "main"
base_commit: "84004163"
claim: "coordination/claims/basket-variants--20260817T235000Z-aios-arena.md (снят при завершении)"
---

## Цель

Пассивное крыло — вариации корзины/DCA с честным бэктестом на годовой истории
(решение владельца): частота ребаланса (неделя/месяц/квартал), тренд-фильтр
(BTC vs SMA200), vol-targeting (веса ∝ 1/σ), DCA-варианты. A-priori параметры,
издержки 0.1%/лег, метрики: PnL%, MaxDD, Sharpe, сделки.

## Scope

- scripts/quant_basket_variants.py (новый), tests/test_basket_variants.py,
  docs/BASKET_VARIANTS_2026-08-17_RU.md, coordination/*.
- Вне scope: прод-код; чужие изменения.


## Итог

- Ребаланс-частота не влияет (32-33% в медвежьем окне).
- Vol-targeting: −12.0% vs −33.2% (DD −27.3 vs −39.1) — лучший всегда-в-рынке.
- DCA: −4.7% — в 7 раз лучше lump-sum в медвежьем годе.
- Тренд-фильтр: честный 0% (кэш весь год; BTC не проходил SMA200 ни дня —
  проверено отдельно, warmup-окно вынесено в под-окно B).
- Рекомендации владельцу: vol-targeting в live-корзину; тренд-фильтр как
  уведомление в брифинг; DCA не менять.
- Отчёт docs/BASKET_VARIANTS_2026-08-17_RU.md; тесты 6/6.
