---
name: octopus-memory-copies-audit
description: Octopus memory invariant audit: every local memory object MUST have at least
---

# SKILL: octopus-memory-copies-audit
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Octopus memory invariant audit: every local memory object MUST have at least
one INDEPENDENT off-host copy (vector ПАМЯТЬ / instruction #11).

Independent backends considered (in priority order):
  1. AWS S3 cloud bucket  (off-site, different provider)  -> truly independent
  2. Garage S3            (separate service / may be other node)
  3. IPFS recursive pins  (content-addressed, distributable)

The local "mirror" dir on the SAME host is NOT counted as independent.

Exit code:
  0  -> invariant holds (every local object has >=1 independent copy) or warn-only
  1  -> invariant VIOLATED (objects with zero independent copies) when --strict

Output: single JSON line (machine-readable for smoke test).

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
- Описание назначения: Octopus memory invariant audit: every local memory object MUST have at least one INDEPENDENT off-host copy (vector ПАМЯТЬ / instruction #11). Independent backends considered (in priority order): 1. AWS S3 cloud bucket (off-site, different provider) -> truly independent 2. Garage S3 (separate service
