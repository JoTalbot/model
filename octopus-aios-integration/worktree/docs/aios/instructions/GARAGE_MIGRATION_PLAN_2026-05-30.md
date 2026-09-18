# Garage Migration Plan — Octopus
Обновлено: 2026-05-30 05:34 UTC
Статус: подготовлен, НЕ запускать автоматически

## Цель
Подготовить безопасный переход от текущего режима `standalone + tunnels + rpc allowlist` к настоящему replicated Garage cluster между main и AWS.

## Текущий режим
- main и AWS видят друг друга по RPC (`3901`) через allowlist-only firewall rules
- S3/Admin на обеих нодах localhost-only
- AWS auxiliary APIs идут через tunnels
- preflight: `transport_preflight_ok=true`, `replicated_cluster_ready=false`

## Главные блокеры на сейчас
1. `replication_factor=1` на обеих нодах
2. AWS нода не назначена в layout (`NO ROLE ASSIGNED`)
3. AWS journal периодически сообщает `bad_peers=true`

## Go / No-Go критерии перед change window
### Go только если:
- smoke = green
- alerts firing = 0
- restore drill = OK
- env validator = OK
- `garage status` и `garage layout show` стабильно отвечают
- свежий preflight подтверждает transport/config readiness
- есть актуальные бэкапы PostgreSQL, agents, garage config, state

### No-Go если:
- есть firing alerts
- `bad_peers=true` сохраняется без понимания причины
- layout/role состояние остаётся неясным
- нет rollback-плана и maintenance window

## План миграции (подготовительный, не исполнять вслепую)
### Фаза 0. Freeze / Backup
- зафиксировать текущее состояние `garage status`, `garage layout show`, node ids, configs
- сделать backup:
  - `/etc/garage.toml` на обеих нодах
  - `/var/lib/garage/meta` и state where applicable
  - PostgreSQL dumps
  - `/var/lib/octopus`, `/root/agents`
- зафиксировать окно работ и критерии rollback

### Фаза 1. Устранить ambiguity peer-state
- разобрать источник `bad_peers=true` на AWS
- убедиться, что между нодами только одна ожидаемая peer-path topology
- повторно прогнать preflight

### Фаза 2. Подготовить replicated design
- определить целевой `replication_factor >= 2`
- определить zone/tag/capacity policy для AWS роли
- подтвердить, что двухнодовая схема вообще допустима для нужной zone redundancy и желаемого SLA

### Фаза 3. Layout staging
- staged assign AWS node role в layout
- review staged layout
- отдельный explicit apply только в maintenance window
- после apply: immediate validation `garage status`, `garage layout show`, journal, preflight

### Фаза 4. Post-change validation
- restore drill
- smoke
- alerts
- проверка object operations через Garage / JuiceFS
- проверка, что нет restart-loops и data mismatch

## Rollback plan
Rollback обязателен и должен быть быстрым:
1. остановить дальнейшие cluster changes
2. вернуть предыдущие `garage.toml`
3. вернуть предыдущий безопасный режим `standalone + tunnels + rpc allowlist`
4. проверить `garage.service`, restore drill, smoke, alerts

## Практический вывод
Пока нет необходимости форсировать replicated Garage.
Текущий режим уже достаточно безопасен и функционален:
- память живёт
- AWS участвует как auxiliary replica layer
- внешняя поверхность минимизирована

## Рекомендация на сейчас
- краткосрочно: оставаться в `standalone + tunnels + rpc allowlist`
- среднесрочно: делать topology/health UX и наблюдение
- cluster migration выполнять только отдельной change window-сессией

## Подготовленные change-window assets
- Checklist: `~/agents/-Octopus/instructions/GARAGE_CHANGE_WINDOW_CHECKLIST_2026-05-30.md`
- Snapshot/backup script: `/usr/local/sbin/octopus-garage-freeze-backup.sh`
- Preflight report: `/var/lib/octopus/garage_preflight/latest.json`
