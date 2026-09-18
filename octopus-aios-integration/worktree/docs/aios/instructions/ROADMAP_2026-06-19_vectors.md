# Octopus Roadmap — независимые потоки развития (2026-06-19)

Принцип: развивать систему параллельными, ограниченными и проверяемыми волнами. Платные ресурсы не создавать без явного подтверждения; автономные бесконечные циклы не запускать.

## Поток A — ЖИТЬ / Operability Green
1. Держать `octopus test` = 16/16 и SLO green.
2. Диск parent держать <88%, emergency reserve >4GB.
3. Любой restart-loop чинить сразу; NRestarts ключевых сервисов = 0.
4. Убрать конфликты портов 11434: parent использует ubu-worker Ollama tunnel, локальный Ollama parent выключен.

## Поток B — Память / Durability
1. Packstore readable локально + off-host replicas readable по фактическим enabled targets.
2. EU AWS cost-paused ноды не считать аварийными; тесты должны учитывать `targets` из `/run/octopus/packstore_offhost.json`.
3. Перед удалением любых EBS/volume — только отдельный DR drill + явное подтверждение человека.

## Поток C — Audio/Whisper/People Graph
1. Long audio >300s обрабатывать chunked-small.
2. Ubu-worker — основной remote Whisper; parent fallback только как safety net.
3. Corrupt/unreadable media помечать `status=corrupt`, не ретраить бесконечно.
4. Speaker mapping развивать через `recording_speakers` → ручные/умные aliases → `people/person_relations` только при надёжных именах.

## Поток D — Обучение / Vector/RAG
1. Восстановить/наполнить HNSW/pgvector, сейчас summary показывает `Vectors: 0 ... CHECK`.
2. Индексировать логи/experience/аудио summaries пакетами, с disk guard.
3. Добавить качество поиска: smoke query set, recall snapshots.

## Поток E — Сосуществование с человеком
1. Сохранять `auto-bash=off`, dev-loop inactive, quiet/coexistence limits.
2. CPU/RAM лимиты Whisper/Ollama не повышать без причины.
3. Все тяжёлые задачи — bounded batch + лог результата.

## Поток F — Размножение / Swarm без новых расходов
1. Использовать только уже оплаченные/бесплатные ресурсы: local child nodes, ubu-worker, существующий AWS us node.
2. Новые платные VPS/AWS/Hetzner — только после явного подтверждения в текущей сессии.
3. Для free-tier — фиксировать отсутствие карты/списаний перед созданием.

## Поток G — Security/Access
1. Не логировать секреты; права ключей 600; внешние порты только нужные.
2. Проверять Cloudflare/nginx exposure и Basic/Auth токены.
3. Хранить backup unit/config перед изменениями.

## Поток H — Product/UI/API
1. DevPanel/API health держать зелёным.
2. Вывести понятную страницу аудио: очередь, corrupt files, speaker mapping, темы.
3. Улучшить Telegram bot: команды `/health`, `/ai_health`, `/audio_queue`, `/roadmap`.

## Первая выполненная волна 2026-06-19
- SLO возвращён в green, `octopus test` 16/16.
- Освобождён диск parent: 100% → 86%.
- Исправлен `octopus-tg-bot` SyntaxError/restart-loop.
- Починен Ollama endpoint 11434 через ubu tunnel; локальный hung Ollama parent выключен.
- Тест off-host приведён к cost-safe режиму 1/1 enabled replica.
- Ubu Whisper пересобран совместимо с CPU; invalid opcode устранён.
- Corrupt audio больше не уходит в бесконечные hourly retries.
