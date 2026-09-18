---
name: octopus-dr-drill
description: Octopus Disaster-Recovery Drill (vector #8 ПАМЯТЬ).
---

# SKILL: octopus-dr-drill
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Octopus Disaster-Recovery Drill (vector #8 ПАМЯТЬ).

Симулирует потерю packstore на parent: тянет dict+packs ИЗ off-host реплики
во временную папку и проверяет читаемость N случайных объектов (sha-сверка).
Доказывает: память восстановима и читаема даже при потере parent-копии.

Пишет /run/octopus/dr_drill.json. Exit 0 = успех, 1 = провал (нет читаемой реплики).
Безопасно: только чтение из реплик + локальная scratch, ничего не меняет в проде.

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
- Описание назначения: Octopus Disaster-Recovery Drill (vector #8 ПАМЯТЬ). Симулирует потерю packstore на parent: тянет dict+packs ИЗ off-host реплики во временную папку и проверяет читаемость N случайных объектов (sha-сверка). Доказывает: память восстановима и читаема даже при потере parent-копии. Пишет /run/octopus/dr_d
