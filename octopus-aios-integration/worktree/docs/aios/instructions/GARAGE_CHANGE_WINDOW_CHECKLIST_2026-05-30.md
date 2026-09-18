# Garage Change Window Checklist — Octopus
Обновлено: 2026-05-30 05:34 UTC
Статус: подготовлено, не запускать автоматически

## Перед окном работ
- [ ] smoke = green
- [ ] alerts firing = 0
- [ ] restore drill = OK
- [ ] env validator = OK
- [ ] `garage preflight` обновлён и сохранён
- [ ] подтверждено, нужен ли вообще replicated Garage сейчас
- [ ] согласовано окно работ и rollback plan

## Freeze / Backup
- [ ] выполнить `/usr/local/sbin/octopus-garage-freeze-backup.sh`
- [ ] сохранить путь к snapshot directory
- [ ] убедиться, что там есть local+aws capture, `garage.toml`, `garage status/layout`, firewall rules, journals
- [ ] убедиться, что актуальные стандартные бэкапы Octopus тоже выполнены

## Go / No-Go
### Go только если:
- [ ] `transport_preflight_ok = true`
- [ ] понятна причина `bad_peers=true` или она устранена
- [ ] понятна стратегия layout assign/apply
- [ ] целевой `replication_factor >= 2` согласован

### No-Go если:
- [ ] есть firing alerts
- [ ] `bad_peers` остаётся непонятным
- [ ] нет полного snapshot/rollback evidence
- [ ] нет maintenance window

## Во время окна работ
- [ ] staged layout assign
- [ ] review staged layout
- [ ] explicit apply только после review
- [ ] сразу после apply проверить `garage status`, `garage layout show`, journal
- [ ] проверить, что нет restart-loop и data mismatch

## После окна работ
- [ ] restore drill
- [ ] smoke
- [ ] alerts
- [ ] проверка UI `/admin/memory` и `/admin/memory/health`
- [ ] обновить COMPACT_CONTEXT и project logs
