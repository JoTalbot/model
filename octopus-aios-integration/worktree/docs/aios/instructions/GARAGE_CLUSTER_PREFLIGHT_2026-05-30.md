# Garage Cluster Preflight — Octopus
Обновлено: 2026-05-30 05:34 UTC

Источник отчета: `/var/lib/octopus/garage_preflight/latest.json`

## Итоговый вердикт
- `transport_preflight_ok = true`
- `replicated_cluster_ready = false`
- Рекомендуемый режим сейчас: **standalone_plus_tunnel**

## Что уже зелёное
- `garage.service` активен на main и AWS.
- Full node IDs различаются и видны корректно.
- `rpc_secret` совпадает.
- `replication_factor` совпадает между main и AWS.
- `3901/tcp` доступен в обе стороны по allowlist между main и AWS.
- S3/Admin на обеих нодах уже localhost-only.
- `garage status/layout show` на main снова работают после добавления self-IP allow rules.
- Preflight больше не использует raw TCP probes и не создаёт лишних handshake-error артефактов в journal.

## Что ещё блокирует настоящий replicated cluster mode
1. **`replication_factor = 1` на обеих нодах**
   - это не режим реальной двухкопийной репликации между main и AWS.
2. **AWS нода не назначена в layout**
   - strict cluster enablement всё ещё требует staged `layout assign/apply`.
3. **AWS journal всё ещё сообщает `bad_peers=true`**
   - discovery/peer-состояние ещё неоднозначно для безопасного cluster enablement.

## Практический вывод
- Transport/config уровень приведён в порядок и защищён allowlist-правилами.
- Настоящий replicated Garage cluster сейчас **включать нельзя** без отдельного migration plan.
- Подготовленный план лежит в: `~/agents/-Octopus/instructions/GARAGE_MIGRATION_PLAN_2026-05-30.md`

## Следующие безопасные шаги
1. Решить целевой режим:
   - либо оставить `standalone + tunnels + rpc allowlist`,
   - либо готовить настоящий replicated cluster.
2. Если нужен replicated cluster:
   - сделать backup и change window;
   - спроектировать переход на `replication_factor >= 2`;
   - подготовить layout assign/apply для AWS-ноды;
   - повторно прогнать preflight.
3. Если cluster mode не нужен прямо сейчас:
   - текущий allowlist для `3901` уже является безопасным промежуточным режимом.
4. Для change window уже подготовлены:
   - `~/agents/-Octopus/instructions/GARAGE_CHANGE_WINDOW_CHECKLIST_2026-05-30.md`
   - `/usr/local/sbin/octopus-garage-freeze-backup.sh`
