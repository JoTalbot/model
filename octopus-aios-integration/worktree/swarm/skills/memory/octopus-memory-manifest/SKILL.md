---
name: octopus-memory-manifest
description: Octopus: ежедневный manifest sha256 для каждого backend.
---

# SKILL: octopus-memory-manifest
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Octopus: ежедневный manifest sha256 для каждого backend.
Собирает отсортированный список sha-объектов с каждого backend,
считает sha256(json([sha1, sha2, ...])) — это "манифест-хэш" backend'а.
Сравнивает манифесты между backends — при расхождении (списка) показывает,
сколько лишних/недостающих с каждой стороны и алертит в TG.

Backends:
  - local: /var/lib/octopus/memory_pool (ls)
  - aws_s3: aws s3 ls (постранично)
  - aws_ec2_node: ssh + ls

Сохраняет manifest_<backend>_<sha>.json в /var/lib/octopus/manifests/.
Это даёт "доказательство времени" + быстрый аудит целостности.

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
- Описание назначения: Octopus: ежедневный manifest sha256 для каждого backend. Собирает отсортированный список sha-объектов с каждого backend, считает sha256(json([sha1, sha2, ...])) — это "манифест-хэш" backend'а. Сравнивает манифесты между backends — при расхождении (списка) показывает, сколько лишних/недостающих с каж

## Policy update 2026-06-30
- Direct Telegram push from this legacy/runtime path запрещён.
- Уведомления и отчёты должны идти через approved control-plane, `skill-notification`, audit-logs или reports.
- Для DR/memory задач приоритет: сохранить логику проверки/восстановления, но исключить scattered direct Telegram sender code.
