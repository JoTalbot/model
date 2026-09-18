---
name: octopus-alerting
description: Octopus Alerting Daemon v2 (2026-05-18).
---

# SKILL: octopus-alerting
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Octopus Alerting Daemon v2 (2026-05-18).

Изменения:
- Источник нод — /var/lib/octopus/nodes.json (единый Node Registry).
  Fallback: legacy hardcoded NODES (compat).
- Различает состояния: ok / degraded / unreachable / quarantined.
- Throttling: алерт по одной ноде не чаще 1 раза в 5 минут.
- Отдельный warning, если нода в quarantine больше 1 часа (раз в час).
- Telegram сообщения с эмодзи и контекстом.
- Persistent state в /var/lib/octopus/alerting-state.json (по желанию).

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
- Описание назначения: Octopus Alerting Daemon v2 (2026-05-18). Изменения: - Источник нод — /var/lib/octopus/nodes.json (единый Node Registry). Fallback: legacy hardcoded NODES (compat). - Различает состояния: ok / degraded / unreachable / quarantined. - Throttling: алерт по одной ноде не чаще 1 раза в 5 минут. - Отдельны
