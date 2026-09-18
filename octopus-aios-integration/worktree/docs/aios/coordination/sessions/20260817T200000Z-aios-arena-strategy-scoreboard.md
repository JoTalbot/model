---
session_id: "20260817T200000Z-aios-arena-strategy-scoreboard"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T20:00:00Z"
updated_utc: "2026-08-17T20:20:00Z"
branch: "agent/20260817-strategy-scoreboard"
base_commit: "1b4aac6e"
claim: "coordination/claims/strategy-scoreboard--20260817T200000Z-aios-arena.md (снят при завершении)"
---

## Цель

Решение «как лучше» (делегировано владельцем): M2 в paper НЕ ставить; вместо
этого автоматизировать ежемесячный бэктест стратегий (scoreboard).

## Итог

- scripts/quant_strategy_scoreboard.py: прогоняет оба харнесса с развёрнутыми
  параметрами, пишет строку в data/reports/strategy_scoreboard.jsonl + MD-таблицу.
  Механическое правило вердикта (см. docs/STRATEGY_SCOREBOARD.md).
- Таймер aios-strategy-scoreboard: ежемесячно 2-го числа 06:10 UTC (Persistent).
- Первая строка (2026-08, свежее окно): DV2 −0.38% (9 сд.), корзина топ-10
  +2.51% (n=9, TON отсутствует в binance-срезе), рынок −7.35%, M2 +1.7%.
  Вердикт: **top10_basket** — корзина лучше всех активных и положительна.
- Обработка неполноты данных: корзина считается при >=8/10 активов; иначе
  fallback на среднюю рынка (для вердикта), в таблице «—».
- Тесты 8/8 (парсер, корзина, вердикт-правила, rebuild); аудит systemd 0 drift;
  inventory актуален.

## Изменённые файлы

- scripts/quant_strategy_scoreboard.py (новый), tests/test_quant_strategy_scoreboard.py (новый),
  deploy/systemd/aios-strategy-scoreboard.{service,timer} (новые),
  deploy/systemd/HETZNER_INSTALLED_UNITS.txt (168), tests/test_systemd_inventory.py,
  docs/STRATEGY_SCOREBOARD.md (новый), docs/PROJECT_INVENTORY.md, coordination/*.

## Git

- Коммит: 8455f8a9 (ветка agent/20260817-strategy-scoreboard).

## Handoff

- Следующий шаг: следующий прогон автоматически 02.09; если M2 будет стабильно
  выигрывать И его OOS выйдет в плюс — вердикт сменится сам.
- Риски: нет новых.
