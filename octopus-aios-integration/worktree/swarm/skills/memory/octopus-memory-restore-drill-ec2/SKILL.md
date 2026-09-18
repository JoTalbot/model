---
name: octopus-memory-restore-drill-ec2
description: Octopus: restore-drill для AWS EC2-ноды (через SSH+sha256sum).
---

# SKILL: octopus-memory-restore-drill-ec2
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Octopus: restore-drill для AWS EC2-ноды (через SSH+sha256sum).
Дополняет существующий restore-drill (только AWS S3).
Берёт 5 случайных объектов, для каждого:
  - читает локальный sha256
  - ssh ubuntu@AWS_HOST "sha256sum /var/lib/octopus/memory_pool/<sha>"
  - сверяет
Алертит в Telegram при расхождении.

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
- Описание назначения: Octopus: restore-drill для AWS EC2-ноды (через SSH+sha256sum). Дополняет существующий restore-drill (только AWS S3). Берёт 5 случайных объектов, для каждого: - читает локальный sha256 - ssh ubuntu@AWS_HOST "sha256sum /var/lib/octopus/memory_pool/<sha>" - сверяет Алертит в Telegram при расхождении.

## Policy update 2026-06-30
- Direct Telegram push from this legacy/runtime path запрещён.
- Уведомления и отчёты должны идти через approved control-plane, `skill-notification`, audit-logs или reports.
- Для DR/memory задач приоритет: сохранить логику проверки/восстановления, но исключить scattered direct Telegram sender code.
