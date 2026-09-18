# Octopus Backup/Restore Compatibility Contract — 2026-05-31

## Purpose
This document defines the stable backup artifact contract for Octopus restore drills and future backup-manager changes.

## Accepted backup directory layout
A backup directory lives under:

```text
/var/backups/octopus/YYYYMMDD-HHMMSS/
```

Restore tooling MUST accept both formats below.

### Legacy format
```text
postgres.sql.gz
agents.tar.gz
configs.tar.gz
octopus_state.tar.gz
MANIFEST.txt optional
```

Expected content:
- `postgres.sql.gz`: PostgreSQL dump restorable into an empty DB.
- `agents.tar.gz`: `/root/agents` context and project logs/instructions.
- `configs.tar.gz`: service/config snapshots.
- `octopus_state.tar.gz`: must contain `var/lib/octopus/nodes.json` or equivalent state.

### Unified format
```text
postgres_full.sql.gz
agents_configs.tar.gz
memory_state.tar.gz
```

Expected content:
- `postgres_full.sql.gz`: PostgreSQL dump restorable into an empty DB.
- `agents_configs.tar.gz`: combined agents + configs + systemd/nginx snapshots.
- `memory_state.tar.gz`: must contain `nodes.json` and `memory_pool/`.

## Compatibility rules
1. `/opt/octopus-restore-drill.sh` is the compatibility adapter and MUST remain able to restore/check both formats.
2. Backup-manager MAY change internal names only if restore-drill is updated in the same change window.
3. Smoke uses restore-drill as the source of truth; therefore backup changes must end with:
   ```bash
   /opt/octopus-restore-drill.sh
   systemctl start octopus-smoke.service
   journalctl -u octopus-smoke -n 80 --no-pager
   ```
4. A valid restore drill requires:
   - PostgreSQL dump parses and restores to `octopus_drill`.
   - `agent_memory >= 10`.
   - `experience_index >= 5`.
   - `nodes.json` is present and has at least one node.
5. Backups are never deleted manually by agents except via documented rotation policy.

## Current status (2026-05-31 WAVE-13)
- Latest backup tested: `20260531-000015`.
- Format: unified.
- Restore drill: OK.
- Smoke after compatibility fix: 40 pass / 0 warn / 0 fail.

## Future recommendation
Prefer keeping unified names, but treat restore-drill as a stable API. If external tools consume backups, expose a generated `MANIFEST.json` with canonical logical artifact names:

```json
{
  "postgres": "postgres_full.sql.gz",
  "agents_configs": "agents_configs.tar.gz",
  "state": "memory_state.tar.gz",
  "format": "unified-v1"
}
```
