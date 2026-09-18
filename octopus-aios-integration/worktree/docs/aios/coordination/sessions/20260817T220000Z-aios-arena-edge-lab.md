---
session_id: "20260817T220000Z-aios-arena-edge-lab"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T22:00:00Z"
updated_utc: "2026-08-17T22:45:00Z"
branch: "agent/20260817-edge-lab"
base_commit: "d216cc73"
claim: "coordination/claims/edge-lab--20260817T220000Z-aios-arena.md (снят при завершении)"
---

## Цель

Новый виток Edge Lab: (1) triple-barrier метки, (2) бенчмарк-корзина топ-10,
(3) power-анализ A/B, (4) инфра-хвосты.

## Итог

1. **Triple-barrier ОТКЛОНЁН:** tb AUC 0.502 vs nb 0.524 (35 символов,
   purge-сплит, те же фичи/гиперпараметры). Метки не были узким местом —
   сигнала в технических фичах на 1h нет. Направление «лучшие метки» закрыто.
   Харнесс scripts/quant_ml_triple_barrier.py переиспользуем (purge обязателен).
   Отчёт: docs/EDGE_LAB_TRIPLE_BARRIER_2026-08-17_RU.md; тесты 6/6.
2. **Бенчмарк-корзина топ-10 в paper:** scripts/run_basket_paper.py (ежедневная
   маркировка, месячный ребаланс, fee 0.1%/лег, старт $1000) + таймер
   aios-basket-paper (ежедневно 17:40 UTC). Первая точка: $1000, fee $1.
   Тесты 3/3.
3. **Power-анализ A/B:** required_trades_for_power в quant_ab_report.py —
   честная цифра: эффект 0.2$/сд. при sd 2.0 требует ~1237 сделок/контур
   (при текущем темпе ~1/день это годы) → практический вердикт по 15-20
   сделкам даёт экономический сигнал, а не строгую значимость; отражено в
   тексте weekly-отчёта. Бенчмарк-строка корзины добавлена в TG-отчёт.
   Тесты 4/4.
4. Инфра: юниты + inventory-снапшот 170.

## Изменённые файлы

- scripts/quant_ml_triple_barrier.py, tests/test_triple_barrier.py (новые).
- scripts/run_basket_paper.py, tests/test_basket_paper.py (новые).
- scripts/quant_ab_report.py (+power, +basket), tests/test_ab_power_basket.py (новые).
- deploy/systemd/aios-basket-paper.{service,timer} (новые), HETZNER_INSTALLED_UNITS.txt (170),
  tests/test_systemd_inventory.py, docs/EDGE_LAB_TRIPLE_BARRIER_2026-08-17_RU.md,
  docs/PROJECT_INVENTORY.md, coordination/*.

## Проверки

- [PASS] целевые тесты: triple-barrier 6/6, basket 3/3, power/basket 4/4, ab-report.
- [PASS] полный pytest: единственный провал — stale inventory (перегенерирован).

## Git

- Коммит: 03cd77a9 (ветка agent/20260817-edge-lab).

## Handoff

- Следующий шаг: полный pytest → PR → мерж; наблюдение за корзиной и A/B.
