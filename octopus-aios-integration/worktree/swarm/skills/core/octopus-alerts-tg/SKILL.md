---
name: octopus-alerts-tg
description: Octopus Prometheus Alerts → Telegram bridge (2026-05-18).
---

# SKILL: octopus-alerts-tg
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Octopus Prometheus Alerts → Telegram bridge (2026-05-18).

Зачем: Prometheus сам по себе не отправляет alerts. Это легковесная замена
Alertmanager для нашего скромного объёма (≤10 алертов/час).

Логика:
1. Каждые ALERT_POLL_SEC секунд тянем `/api/v1/alerts` у локального Prometheus.
2. Считаем "active fingerprint" = sha1(alertname + labels-sorted).
3. Состояние держим в /var/lib/octopus/alerts-tg-state.json:
   { fp: {"name":..., "labels":..., "first_seen":..., "last_sent":..., "state":"firing|resolved"} }
4. Действия:
   - новый firing → шлём в TG, last_sent=now, state=firing
   - всё ещё firing и прошло > RESEND_FIRING_SEC от last_sent → шлём reminder
   - был firing, теперь отсутствует → шлём "✅ resolved" → state=resolved, держим ещё 6ч и чистим
5. Healthz на 127.0.0.1:9716/healthz.

ENV:
- PROMETHEUS_URL (default http://127.0.0.1:9090)
- TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_IDS
- ALERT_POLL_SEC (default 60)
- RESEND_FIRING_SEC (default 3600) — повтор напоминания о всё ещё активном алерте
- DRY_RUN=1 — не слать в TG, только лог.

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
- Описание назначения: Octopus Prometheus Alerts → Telegram bridge (2026-05-18). Зачем: Prometheus сам по себе не отправляет alerts. Это легковесная замена Alertmanager для нашего скромного объёма (≤10 алертов/час). Логика: 1. Каждые ALERT_POLL_SEC секунд тянем `/api/v1/alerts` у локального Prometheus. 2. Считаем "active
