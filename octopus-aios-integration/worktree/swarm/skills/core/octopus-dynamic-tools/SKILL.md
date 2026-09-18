---
name: octopus-dynamic-tools
description: octopus-dynamic-tools — Phase D5 prep: policies + load-aware scheduler.
---

# SKILL: octopus-dynamic-tools
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
octopus-dynamic-tools — Phase D5 prep: policies + load-aware scheduler.

D4 endpoints: /capabilities/*.
D5 NEW endpoints (READ-ONLY, no consent needed):
- GET /policies                — list all policy files
- GET /policies/<name>         — contents of a policy file
- POST /policy/evaluate        — evaluate all policies against current state, return allow/stop/refuse per target
- POST /policy/evaluate/<name> — evaluate specific policy

Policy YAML format:
  name: <name>
  description: <text>
  priority: high|medium|low
  rules:
    - id: <rule-id>
      condition: "<python-expression-with-state>"
      action: allow | stop | refuse
      targets: [<list-of-service-short-names>]
      reason: <human-readable>

Condition uses variables from current_state:
  load_1min, load_5min, load_15min (float)
  memory_used_pct (float)
  disk_used_pct (float)
  disk_free_gb (float)
  hour_utc (int, 0-23)
  current_mode (str)

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
- Описание назначения: octopus-dynamic-tools — Phase D5 prep: policies + load-aware scheduler. D4 endpoints: /capabilities/*. D5 NEW endpoints (READ-ONLY, no consent needed): - GET /policies — list all policy files - GET /policies/<name> — contents of a policy file - POST /policy/evaluate — evaluate all policies against c
