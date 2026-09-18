---
session_id: "20260817T133000Z-aios-arena-btc-long-horizon"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T13:30:00Z"
updated_utc: "2026-08-17T14:05:00Z"
branch: "agent/20260817-trading-improvements"
base_commit: "2948222d"
claim: "coordination/claims/btc-long-horizon--20260817T133000Z-aios-arena.md (снят при завершении)"
---

## Цель

Строгая OOS-проверка BTC long-horizon сигнала (AUC 0.63-0.66 на 180-900с из
MM interim-2) с purge-сплитом, страйдом и атрибуцией фич.

## Итог

Гипотеза ОТКЛОНЕНА: на purge-сплите AUC 0.49-0.56 (не 0.63-0.66) — исходная
оценка была утечкой лейблов через перекрывающиеся окна без purge-гэпа.
Orderbook-фичи не добавляют к моментуму; long-стратегия (q90 порог) net of
0.5% cost отрицательна на всех горизонтах (−0.41…−0.48% за сделку).
Единственный намёк H=60с (AUC 0.617) экономически незначим.

## Изменённые файлы

- scripts/mm_signal_long_horizon_check.py — новый строгий чекер (purge-сплит, страйд, бутстрап).
- tests/test_mm_signal_long_horizon.py — 5 тестов чистых функций.
- docs/BTC_LONG_HORIZON_SIGNAL_2026-08-17_RU.md — отчёт-вердикт.
- coordination/* — журнал, claim, PROJECT_CONTEXT.

## Проверки

- [PASS] pytest tests/test_mm_signal_long_horizon.py 5/5.
- [PASS] полный прогон: 5 горизонтов × 3 набора фич + стратегия (17 фитов).

## Git

- Коммит: 57ded2b7.

## Handoff

- Следующий шаг: ждать полных 2-4 недель 1Гц для финального MM-вердикта;
  purge-методика обязательна для любых будущих OOS-заявлений о сигналах.
- Риски: нет.
