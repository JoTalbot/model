---
name: memory-systems
description: Persistent semantic memory, entity tracking, temporal validity, hybrid CAS+vector+graph. Use for people_graph, immortal memory, packstore. Priority ПАМЯТЬ.
---
# Memory Systems (adapted from muratcankoylan)
## Layers
- Working: context
- Short: /var/lib/octopus/memory_pool + scratch
- Long: CAS packstore + pgvector
- Entity: people_graph
- Temporal: GraphRAG + validity

## Workflow
1. Route to shallowest viable layer.
2. Consolidation on threshold or schedule.
3. Hybrid retrieval (semantic + graph).
4. Eternal-drill for durability.

## Описание
Базовое описание функционала.

## Инструкции
1. Изучить код.
2. Выполнить проверку.

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
- Описание назначения: Persistent semantic memory, entity tracking, temporal validity, hybrid CAS+vector+graph. Use for people_graph, immortal memory, packstore. Priority ПАМЯТЬ.
