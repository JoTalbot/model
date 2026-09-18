---
name: octopus-memory-replicator
description: UPDATE memory_records mr
---

# SKILL: octopus-memory-replicator
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
UPDATE memory_records mr
            SET replication_count = (
                SELECT 1 +
                       CASE WHEN EXISTS (SELECT 1 FROM memory_replication_status mrs WHERE mrs.ref = mr.ref AND mrs.node_id = 'local_cluster')
                            THEN 4 ELSE 0 END +
                       (SELECT count(*) FROM memory_replication_status mrs WHERE mrs.ref = mr.ref AND mrs.node_id != 'local_cluster')
            )
            WHERE mr.ref IN (SELECT ref FROM memory_replication_status)

## Инструкции
1. Определить цель навыка.
2. Реализовать логику.
3. Добавить тесты.

## Алгоритм
1. Загрузить `SKILL.md`, контекст проекта Octopus и последние отчёты по направлению навыка.
2. Классифицировать навык по тегам (health/api/memory/disk/telegram/systemd/docker/security/ai).
3. Выполнить только безопасные read-only проверки через `code/run.py` и общий `generic_skill_runtime`.
4. Сформировать JSON-отчёт: статус, найденные факты, риски, рекомендации, следующий bounded-шаг.
5. Если требуется изменение системы — записать proposal/rollback в logs/reports и ждать consent gate либо выполнения автономным агентом в bounded-режиме.
6. Для Telegram: прямые push-уведомления запрещены, кроме `skill-notification` и отчётов автономного агента.
7. Для AWS/платных ресурсов: только аудит; создание/включение ресурсов запрещено без явной команды человека.

## Контроль и развитие
- Runtime: `code/run.py --json`.
- Contract tests: `tests/test_contract.py`.
- Мониторинг: `scripts/skill_evolution_cycle.py` пересчитывает health/coverage и дописывает AI-предложения в `references/`.
- Развитие через ИИ: локальный Ollama/Qwen генерирует bounded improvement proposal; автоприменяются только безопасные структурные улучшения (алгоритм, тест, runtime wrapper).
- Описание назначения: UPDATE memory_records mr SET replication_count = ( SELECT 1 + CASE WHEN EXISTS (SELECT 1 FROM memory_replication_status mrs WHERE mrs.ref = mr.ref AND mrs.node_id = 'local_cluster') THEN 4 ELSE 0 END + (SELECT count(*) FROM memory_replication_status mrs WHERE mrs.ref = mr.ref AND mrs.node_id != 'loc
