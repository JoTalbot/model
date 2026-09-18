---
session_id: "20260817T113000Z-aios-arena-ws-stream-split"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-17T11:30:00Z"
updated_utc: "2026-08-17T11:55:00Z"
branch: "agent/20260817-trading-improvements"
base_commit: "fa05894e"
claim: "none (микро-задача в одном файле, выполнена атомарно за одну сессию; claim-протокол для этого scope признан избыточным, отмечено в журнале)"
---

## Цель

Разнести depth и aggTrade по отдельным WebSocket-соединениям, чтобы всплески
сделок не затапливали поток глубины и не завышали измеряемую latency.

## Итог

- consume_trades: отдельное соединение aggTrade (latency из E + флеш trades_ws 5с).
- consume_one: только depth; latency из shared-состояния с 10с-гейтом (snapshot_latency, чистая функция).
- run_one: два соединения на пару (38 стримов суммарно, лимит Binance 1024/IP), gather 4 задач, реконнект при ошибке любого.
- Результат замера (2.5 мин после рестарта):
  BTC: median 123.1, p90 158.1 (было ~3055), p99 733.8, max 2237.8
  ETH: median 123.6, p90 133.2 (было ~3169), p99 1352.7, max 1775.7
  full-стрим не просел (610 сэмпл/60с на пару), trades_ws 507 строк/5 мин, 0 ошибок.

## Проверки

- [PASS] py_compile scripts/collect_orderbook_ws.py.
- [PASS] pytest tests/test_collect_orderbook_ws.py — 4/4 (добавлен snapshot_latency gating).
- [PASS] рестарт aios-orderbook-ws, все 19 пар depth+trades, 0 ошибок за 3 мин.
- [PASS] сервис active.

## Git

- Коммит: fbb70a5f (ветка agent/20260817-trading-improvements, не опубликована).

## Handoff

- Следующий шаг: через 2-4 недели MM-вердикт на чистых ws-данных (latency теперь честная).
- Риски: 38 стримов против 19 — лимиты Binance далеко не выбраны; при проблемах
  rate-limit Binance сам закроет соединение, реконнект отработает.
