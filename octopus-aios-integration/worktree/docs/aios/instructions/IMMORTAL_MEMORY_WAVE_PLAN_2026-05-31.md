# IMMORTAL MEMORY — WAVE EXECUTION PLAN (2026-05-31)
Приоритет: ПАМЯТЬ > ЖИТЬ > УПРОЩЕНИЕ > СОСУЩЕСТВОВАНИЕ

##已完成 (WAVE 1-18)
- WAVE-1: Docker prune, logrotate, coverage-alert timer
- WAVE-2: DB retention, restore-drill-ec2, offline-snapshot
- WAVE-3: Secrets vault, fail2ban, manifest, packstore dry-run, CAS-API
- WAVE-4: Corrupt fix, pack-reader, UI search/lookup/stats
- WAVE-5-18: UI polish, Ops tab, parallel-50 checks, SLO integration

## WAVE-19: Plain-text ops summary + mobile copy
Цель: Endpoint /cas/ops/summary.txt для быстрого copy/paste в Telegram
- [ ] Создать endpoint с plain-text форматом
- [ ] UI: кнопка "Copy status" в Ops tab
- [ ] Smoke: проверить формат

## WAVE-20: Packstore v2 benchmark
Цель: Сравнить zstd levels для pack compression
- [ ] Benchmark zstd-1..22 на sample (1000 объектов)
- [ ] Замер: ratio, compress time, decompress time
- [ ] Рекомендация: optimal level для prod

## WAVE-21: ACL groups в UI
Цель: UI для управления ACL groups
- [ ] UI: список групп, add/remove tokens
- [ ] API: /cas/acl/groups (read), /cas/acl/grant (admin)
- [ ] Smoke: проверить создание группы

## WAVE-22: Backup-restore drill
Цель: Автоматический drill восстановления из backup
- [ ] Скрипт drill на чистом контейнере
- [ ] Timer: weekly
- [ ] TG-алерт при fail

## WAVE-23: Pack-aware replicator
Цель: Репликация pack-файлов вместо loose
- [ ] Pack-aware http-replicator
- [ ] Двойная запись (loose + pack)
- [ ] Smoke: проверить sync

## WAVE-24: GC loose (safe)
Цель: Удаление loose после подтверждения в pack + 3 копии
- [ ] Скрипт GC с dry-run
- [ ] Проверка: pack + 3 копии
- [ ] Manual confirmation required

## Метрики успеха
- Smoke: 40/0/0
- Coverage: 1.0
- SLO: green
- NRestarts: 0
