---
name: dna-sharding-guard
description: Erasure coding for Octopus memory DNA. Splits CAS/packstore data into 5 shards
---

# SKILL: dna-sharding-guard
**Category:** core
**Status:** ACTIVE (on-demand + scheduled)
**Created:** 2026-06-19 (Batch 85, Phase 8 upgrade)
**Path:** /opt/octopus-dna-erasure-coding.py
**Shards:** /var/lib/octopus/snapshots/shards/dna_shard_XX

## Description
Erasure coding for Octopus memory DNA. Splits CAS/packstore data into 5 shards
using Reed-Solomon over GF(256). Any 3 shards can reconstruct the original data.
Provides quantum-level resilience against data loss.

## Commands
- Create shards: `python3 /opt/octopus-dna-erasure-coding.py`
- Audit shards: `python3 /opt/octopus-dna-erasure-coding.py audit`
- Manifest: `cat /var/lib/octopus/snapshots/shards/dna_manifest.json`

## Distribution
- Shards 0-2: Local (parent node)
- Shards 3-4: Off-host (aws, ubu-worker via multisync)

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
- Описание назначения: Операционный навык Octopus: dna-sharding-guard.
