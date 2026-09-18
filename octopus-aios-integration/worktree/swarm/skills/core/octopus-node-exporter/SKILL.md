---
name: octopus-node-exporter
description: Octopus Node Status Exporter (2026-05-18).
---

# SKILL: octopus-node-exporter
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Octopus Node Status Exporter (2026-05-18).

Лёгкий Prometheus exporter, который читает:
- /var/lib/octopus/nodes.json       — единый Node Registry
- /var/lib/octopus/watchdog-state.json — последний статус по нодам

И отдаёт метрики на 127.0.0.1:9717/metrics:

# HELP octopus_node_status Octopus node status (1=ok, 0=degraded, -1=unreachable, -2=quarantined, -3=unknown)
# TYPE octopus_node_status gauge
octopus_node_status{id="parent-8000",label="parent-8000",role="parent",external="false",ip="127.0.0.1"} 1
# HELP octopus_node_quarantined 1 if node is marked quarantined in registry
# TYPE octopus_node_quarantined gauge
octopus_node_quarantined{...} 0/1
# HELP octopus_node_enabled
# TYPE octopus_node_enabled gauge
octopus_node_enabled{...} 0/1
# HELP octopus_watchdog_consecutive_failures
# TYPE octopus_watchdog_consecutive_failures gauge
octopus_watchdog_consecutive_failures{...} N
# HELP octopus_watchdog_restart_attempts_total
# TYPE octopus_watchdog_restart_attempts_total counter
octopus_watchdog_restart_attempts_total{...} N
# HELP octopus_node_registry_total
# TYPE octopus_node_registry_total gauge
octopus_node_registry_total N

Также /healthz на 9717 (через octopus_healthz).

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
- Описание назначения: Octopus Node Status Exporter (2026-05-18). Лёгкий Prometheus exporter, который читает: - /var/lib/octopus/nodes.json — единый Node Registry - /var/lib/octopus/watchdog-state.json — последний статус по нодам И отдаёт метрики на 127.0.0.1:9717/metrics: # HELP octopus_node_status Octopus node status (1
