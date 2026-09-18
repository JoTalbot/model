---
name: cas-pack-guard
description: Enforce pack_read_guard, zstd.dict verification, SHA integrity for CAS/packstore. Use for all memory writes, eternal snapshots, pack replication. Priority ПАМЯТЬ.
---
# CAS Pack Guard Skill for Octopus

## Описание

Этот скил предназначен для...
## Activation
Use on any CAS write, pack read, eternal-drill, multisync.

## Workflow
1. Check /run/octopus/pack_read_guard.json (sampled >=100/100)
2. Verify zstd.dict present and versioned in pack header.
3. SHA256 after decompress on read.
4. On fail: terminal (corrupt=terminal), alert TG, refuse write.
5. Log to /run/octopus/packstore_offhost.json
6. For eternal: embed dict in snapshot tar.

## References
- /opt/octopus-cas-api.py (pack_index_v2, loose first)
- pack_read_guard 100/100 required

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
- Описание назначения: Enforce pack_read_guard, zstd.dict verification, SHA integrity for CAS/packstore. Use for all memory writes, eternal snapshots, pack replication. Priority ПАМЯТЬ.
