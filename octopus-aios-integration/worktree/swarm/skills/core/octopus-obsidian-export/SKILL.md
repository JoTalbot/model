---
name: octopus-obsidian-export
description: Export Octopus memory (packstore, people_graph, eternal logs) to Obsidian vault format with frontmatter and links. Use for vault-scribe + eternal memory.
---
# Octopus Obsidian Export

## Описание

Этот скил предназначен для...
1. Read CAS objects or memory_pool
2. Generate vault notes with frontmatter (type: memory|person|eternal)
3. Add callouts, links to people_graph
4. Write to /var/lib/octopus/obsidian/
5. Verify SHA + packguard

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
- Описание назначения: Export Octopus memory (packstore, people_graph, eternal logs) to Obsidian vault format with frontmatter and links. Use for vault-scribe + eternal memory.
