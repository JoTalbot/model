set -u
# Read-only preflight for the fresh-host DR / RTO rehearsal (ops/B10_RTO_DR_TEST.md).
# Does not restore, start, stop or delete anything. MadWorld-only scope.
printf '%s\n' 'DR_PREFLIGHT_START'
printf 'HOST=%s NOW=%s\n' "$(hostname)" "$(date -u +%FT%TZ)"
printf '%s\n' 'BACKUP_TIMER='; systemctl is-enabled madworld-backup.timer 2>&1 || true; systemctl is-active madworld-backup.timer 2>&1 || true
systemctl list-timers madworld-backup.timer --no-legend 2>&1 || true
printf '%s\n' 'LATEST_BACKUPS='; ls -lt /opt/madworld/backups/*.dump 2>/dev/null | head -5 || true
printf '%s\n' 'BACKUP_LOG_TAIL='; tail -n 15 /opt/madworld/backups/backup.log 2>/dev/null || true
printf '%s\n' 'MANIFEST='; ls -lt /opt/madworld/backups/*.sha256 /opt/madworld/backups/*manifest* 2>/dev/null | head -5 || true
printf '%s\n' 'DISK='; df -Ph /opt/madworld/backups 2>/dev/null || true
printf '%s\n' 'RELEASE_COMMIT='; git -C /opt/madworld rev-parse HEAD 2>/dev/null || true
printf '%s\n' 'IMAGES='; docker compose -f /opt/madworld/docker-compose.yml images 2>&1 || true
printf '%s\n' 'PG_TOOLS='; command -v pg_restore psql pg_dump 2>&1 || true; docker run --rm postgres:16 pg_restore --version 2>&1 | tail -1 || true
printf '%s\n' 'READY='; curl -fsS --max-time 10 http://127.0.0.1/health/ready 2>&1 || true; printf '\n'
printf '%s\n' 'DR_PREFLIGHT_END'
