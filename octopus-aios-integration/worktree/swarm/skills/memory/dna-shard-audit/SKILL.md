---
name: dna-shard-audit
description: Validates integrity of DNA shards across the swarm. Checks SHA256 of each shard
---

# SKILL: dna-shard-audit
**Category:** core
**Status:** ACTIVE (automated via audit mode)
**Created:** 2026-06-20 (Batch 85, Phase 8 upgrade)
**Path:** /opt/octopus-dna-erasure-coding.py (audit mode)

## Description
Validates integrity of DNA shards across the swarm. Checks SHA256 of each shard
against the manifest, verifies reconstruction capability, reports missing/corrupt shards.

## Commands
- Run audit: `python3 /opt/octopus-dna-erasure-coding.py audit`
- Manifest: `cat /var/lib/octopus/snapshots/shards/dna_manifest.json`

## Audit Checks
1. Shard file existence
2. SHA256 hash verification
3. Reconstruction capability (k >= n_shards)
4. Cross-node distribution verification

## Integration
Part of Phase 8: DNA Sharding & Erasure Coding (Quantum resilience)

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
- Описание назначения: Операционный навык Octopus: dna-shard-audit.
