---
session_id: "20260817T143000Z-aios-arena-mm-queue-model"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T14:30:00Z"
updated_utc: "2026-08-17T15:20:00Z"
branch: "agent/20260817-trading-improvements"
base_commit: "dd22db2d"
claim: "coordination/claims/mm-queue-model--20260817T143000Z-aios-arena.md (снят при завершении)"
---

## Цель

Эмпирическая модель очереди исполнения для MM на ws-данных (решение владельца
«делай всё»): время жизни тача, объём проторговки, fill-вероятность хвоста очереди.

## Итог

- scripts/mm_queue_model.py: тач-события из snapshots_ws + 5с-бакеты trades_ws,
  отбраковка амбивалентных бакетов, fill-модель «хвост очереди» (P(cum vol ≥ S+Q)).
- Результаты: мажоры life_med 5.6-11.4с; P(fill) за 60с в хвосте очереди:
  BTC 18.1%, ETH 18.0%, BNB 30.9% (лучший), LINK 6.9-24.1% (зависит от Q),
  тонкие книги NEAR/ADA 3.8-7.3%. Вывод согласован с interim-2: даже при филле
  adverse selection съедает спред — положительного ожидания нет ни на одной паре.
- Отчёт: docs/MM_QUEUE_MODEL_2026-08-17_RU.md; тесты 3/3.
- Публикация: ветка agent/20260817-trading-improvements (25 коммитов) запушена
  в origin (решение владельца).

## Проверки

- [PASS] pytest tests/test_mm_queue_model.py 3/3.
- [PASS] полный pytest: единственный провал — stale PROJECT_INVENTORY (перегенерирован, зелёный).
- [PASS] audit_deployment_sources.py --runtime --strict: 0 drift.
- [PASS] git push -u origin (new branch).

## Git

- Коммиты: 0570104c, e4691e5c (+ предыдущие 23).
- Ветка опубликована: origin/agent/20260817-trading-improvements.

## Handoff

- Следующий шаг: финальный MM-вердикт после 2-4 недель 1Гц; приоритет очереди —
  на 100мс-стриме BTC/ETH; maker-rebate проверка для BNB.
- Риски: нет.
