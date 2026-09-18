---
name: cas-replication-guard
description: Pack-aware replication + off-host copies + verifiable Merkle for CAS/packstore. Priority ПАМЯТЬ. Use for eternal DR, multisync, immortal memory.
---
# CAS Replication Guard

## Описание

Этот скил предназначен для...
## Workflow
1. Check pack_index + zstd.dict + SHA
2. Replicate pack files + dict to off-host targets
3. Verify composefs / Merkle proofs
4. Integrate with eternal-snapshot + bootstrap
5. Fail on < N independent copies
6. Daily pack_read_guard + off-host check

## References
- /opt/octopus-cas-api.py
- pack_read_guard.json
- eternal-snapshot.py

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
- Описание назначения: Pack-aware replication + off-host copies + verifiable Merkle for CAS/packstore. Priority ПАМЯТЬ. Use for eternal DR, multisync, immortal memory.
