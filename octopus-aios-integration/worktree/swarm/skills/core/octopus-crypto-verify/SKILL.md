---
name: octopus-crypto-verify
description: Crypto-верификация целостности памяти (v2): packs + loose + pack-read sample.
---

# SKILL: octopus-crypto-verify
**Категория:** core
**Дата создания:** 2026-06-20

## Описание
Crypto-верификация целостности памяти (v2): packs + loose + pack-read sample.
После GC данные живут в packstore, поэтому проверяем:
 1) каждый pack-файл против pack_sha256 в БД (bit-rot detection),
 2) выборку объектов РЕАЛЬНЫМ чтением из pack + sha-verify,
 3) loose-пул (если есть) — бонус.
Пишет /run/octopus/crypto_verify.json. exit 1 при любой коррупции.

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
- Описание назначения: Crypto-верификация целостности памяти (v2): packs + loose + pack-read sample. После GC данные живут в packstore, поэтому проверяем: 1) каждый pack-файл против pack_sha256 в БД (bit-rot detection), 2) выборку объектов РЕАЛЬНЫМ чтением из pack + sha-verify, 3) loose-пул (если есть) — бонус. Пишет /run
