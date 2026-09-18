---
name: octopus-full-mcp-guard
description: Guards full MCP server (daemon + RPC + Skills Over MCP), exposes all Octopus tools/resources/skills, ensures SEP-2076 compliance, and handles graceful restart. Use for MCP integration, coexistence, and production exposure.
---
# Octopus Full MCP Guard

## Описание

Этот скил предназначен для...
## Workflow
1. Verify MCP daemon (PID, logs, health)
2. Expose skills/list + skills/get + activate via MCP
3. Bridge CAS, Whisper, RAG, Swarm tools
4. Skills-as-instructors pattern (teach how to use tools)
5. Graceful restart + auto-recovery
6. Rate limiting + ACL from human_consent
7. Log MCP health to /run/octopus/mcp_health.json

## References
- ~/agents/-Octopus/skills/mcp/skills_mcp_server.py
- launch scripts
- Skills Over MCP IG / SEP-2076

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
- Описание назначения: Guards full MCP server (daemon + RPC + Skills Over MCP), exposes all Octopus tools/resources/skills, ensures SEP-2076 compliance, and handles graceful restart. Use for MCP integration, coexistence, and production exposure.

## Read-only operations profile (2026-07-11)
Production MCP bridge exposes bounded closed-world methods:
- `ops/status` — disk and Octopus failed-unit state;
- `storage/proof` — allowlisted live-read proof; secret/SSH/credential paths denied;
- `graphrag/search` — exact source path, indexed SHA256, excerpt and shared trace ID;
- `skills/list`, `skills/get`, `skills/references`.

`tools/list` returns explicit MCP safety annotations: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`. Every call receives or generates `octo-...` trace ID. Integration contract: `tests/test_readonly_ops_mcp.py`.
