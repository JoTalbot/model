---
name: cas-credential-boundary-guard
description: Fail-closed drift guard for CAS credential storage and authentication. It never prints token values.
---

# SKILL: cas-credential-boundary-guard

**Category:** core / security / CAS
**Status:** ACTIVE

## Purpose
Fail-closed drift guard for CAS credential storage and authentication. It never prints token values.

## Algorithm
1. Verify root ownership and mode 0600 for client env and scoped token map.
2. Verify exactly three distinct credentials and scope separation: read, read+write, read+write+admin.
3. Reject inline `Environment=CAS_*_TOKEN` in systemd drop-ins.
4. Verify token names are absent from the CAS process environment.
5. Verify CAS listens only on loopback and service is active.
6. Verify protected endpoint contract: anonymous=401, invalid=401, read credential=200.
7. Emit only booleans and redacted errors.

## Runtime
```bash
python3 code/run.py
```

## Rollback
Sensitive backups remain root-only in `/etc/octopus/secure-backups/`; never copy them into agents, reports, Git or multisync.

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
- Описание назначения: Операционный навык Octopus: cas-credential-boundary-guard.

## Tunnel exposure extension (2026-07-11)
Guard additionally verifies named Cloudflare tunnel token-file usage, absence of inline token in argv/unit, loopback-only CAS and gateway listeners, absence of quick tunnels targeting CAS/gateway, and negative/positive auth canaries through nginx gateway. Current contract: 21 redacted checks.
