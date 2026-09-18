# Octopus Development Roadmap v5 — 2026-05-31

Приоритеты: **ПАМЯТЬ > ЖИТЬ > УПРОЩЕНИЕ > СОСУЩЕСТВОВАНИЕ > безопасность > остальные векторы**. Инструкция #13 соблюдается: никаких внешних нод/платных ресурсов/непроверенных автопетель.

## Независимые потоки
A. **ПАМЯТЬ / Durability**: backup-restore совместимость, restore-drill без false warning, manifest equality, EC2/S3 drills.
B. **SECURITY / Access**: ACL groups, запрет streaming+encrypt footgun, audit analytics, токены без утечек.
C. **UI/UX**: XHR progress upload, Audit summary, mobile/PWA polish, безопасные default-флаги.
D. **PACKSTORE**: safe compaction dry-run, canonical packer-v2 only, no delete without explicit confirmation, future algorithm benchmark (zstd/brotli) only dry-run.
E. **OBSERVABILITY / SLO**: SLO doc + machine-readable checks, smoke 0 fail, контроль NRestarts/ports/orphans.
F. **SIMPLIFICATION**: один путь запуска детей через systemd, единые backup/restore имена или совместимые adapters, меньше legacy scripts.
G. **COEXISTENCE**: лимиты CPU/RAM, loopback-only APIs except tunnel, no port conflicts, no uncontrolled cloud actions.

## Wave-11 execution plan
1. Исправить restore-drill под unified backup format.
2. Исправить CAS streaming upload: Content-Length streaming для браузера; streaming+age запретить.
3. Добавить ACL groups (`X-Acl-Allow-Group`, implicit `scope:*`).
4. Улучшить UI upload progress через XHR + Audit summary.
5. Переписать pack-compaction в safe manager без кастомного ошибочного pack writer.
6. Проверить py_compile, endpoint tests, restore drill, smoke, failed services/NRestarts.

## Wave-12+ backlog
- Named Cloudflare Tunnel: только после предоставления CF account/domain.
- Pack algorithm benchmark: zstd level/dict/brotli на sample, без переключения prod до reader-smoke.
- SLO checker: экспортировать machine-readable `/run/octopus/slo_status.json` и связать с alerting.
- UI: list/search audit browser, share links with ACL group presets.
- Backup: унифицировать имена артефактов в backup-manager или оставить compatibility layer как стабильный API.
