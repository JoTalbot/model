---
session_id: "20260818T010000Z-aios-arena-tg-quant-commands"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-18T01:00:00Z"
updated_utc: "2026-08-18T01:20:00Z"
branch: "agent/20260818-tg-quant-commands"
base_commit: "066fbb80"
claim: "coordination/claims/tg-quant-commands--20260818T010000Z-aios-arena.md (снят при завершении)"
---

## Цель

«+» после best-move: видимость трейдинга с телефона — TG-команды владельцу
(/basket, /ab, /scoreboard) + строки корзины/scoreboard в утренний брифинг.

## Итог

1. tg_bot/quant_cmds.py (не protected): новые cmd_basket/cmd_ab/cmd_scoreboard
   + секции корзины/scoreboard в /quant. cmd_scoreboard graceful при отсутствии
   файла.
2. run_telegram_bot.py (protected): тонкие обёртки + 3 ветки dispatch + help.
   После правки — selfguard --force-snapshot (правило AGENTS).
3. run_morning_brief.py: строки «🧺 Корзина…» и «🏆 Scoreboard…».
   Проверка на реальных данных: A/B 4 vs 3 сделки, корзина $999 (−0.10%),
   scoreboard top10_basket, медвежий режим bear.
4. Попутный фикс корзины: стартовая комиссия платится из депозита (кэш
   заканчивается ровно 0, value $999, fee $1) — раньше кэш уходил в −$1.
5. Тесты: test_tg_quant_cmds.py 5/5; test_basket_paper обновлён.
6. Бот перезапущен (active).

## Изменённые файлы

- tg_bot/quant_cmds.py, run_telegram_bot.py, run_morning_brief.py,
  scripts/run_basket_paper.py, tests/{test_tg_quant_cmds,test_basket_paper}.py,
  docs/PROJECT_INVENTORY.md, coordination/*.

## Проверки

- [PASS] целевые тесты; py_compile всех файлов; selfguard --force-snapshot.
- [PASS] полный pytest: единственный провал — stale inventory (перегенерирован).

## Git

- Коммит: 1c2da1c3 (ветка agent/20260818-tg-quant-commands).

## Handoff

- Следующий шаг: полный pytest → PR → мерж.
