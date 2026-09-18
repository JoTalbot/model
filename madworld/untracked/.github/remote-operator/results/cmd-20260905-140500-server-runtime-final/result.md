# Remote Command Result

- **Command ID:** `cmd-20260905-140500-server-runtime-final`
- **Attempt ID:** `cmd-20260905-140500-server-runtime-final-attempt-20260904T225358Z-951668`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T22:53:58Z`
- **Finished:** `2026-09-04T22:53:59Z`
- **Duration:** `1s`

## Command
```bash
set -euo pipefail
printf '%s\n' 'RUNTIME_FINAL_START'
printf 'HOST=%s\n' "$(hostname)"
printf 'NOW=%s\n' "$(date -u +%FT%TZ)"
printf 'GIT_HEAD=%s\n' "$(git -C /opt/madworld rev-parse HEAD 2>/dev/null || echo unknown)"
printf 'GIT_MAIN=%s\n' "$(git -C /opt/madworld rev-parse origin/main 2>/dev/null || echo unknown)"
printf 'GIT_STATUS=%s\n' "$(git -C /opt/madworld status --short --branch 2>/dev/null || echo unknown)"
printf 'HEALTH='; curl -fsS --max-time 10 http://127.0.0.1/health 2>&1 || true; printf '\n'
printf 'READINESS='; curl -fsS --max-time 10 http://127.0.0.1/health/ready 2>&1 || true; printf '\n'
printf '%s\n' 'CONTAINERS='
docker compose -f /opt/madworld/docker-compose.yml ps 2>&1 || docker ps --format '{{.Names}} {{.Status}}'
printf '%s\n' 'FAILED_UNITS='; systemctl --failed --no-legend 2>&1 || true
printf '%s\n' 'OPERATOR='; systemctl is-active madworld-remote-operator.service 2>&1 || true
printf '%s\n' 'SYNC_TIMER='; systemctl is-active madworld-remote-operator-sync.timer 2>&1 || true
printf '%s\n' 'RUNTIME_FINAL_END'
```

## STDOUT
```text
RUNTIME_FINAL_START
HOST=arm-server-01
NOW=2026-09-04T22:53:58Z
GIT_HEAD=b66e1ec3afa0d3796e9a5fd4eafb5107d5d9fac5
GIT_MAIN=46476d020ab3c504f10f59f696ebb4be42964e1f
GIT_STATUS=## main...origin/main [behind 11]
 M .github/remote-operator/COMMANDS.txt
 M .github/workflows/deploy-on-push.yml
 M AGENTS.md
 M docs/REMOTE_OPERATOR.md
 M docs/REMOTE_OPERATOR_INSTALL.md
?? .github/remote-operator/results/cmd-20260904-220309-operator-test/
?? .github/remote-operator/results/cmd-20260904-220600-home-tree/
?? .github/remote-operator/results/cmd-20260904-220900-operator-delivery-diagnostic/
?? .github/remote-operator/results/cmd-20260905-005600-server-status/
?? .github/remote-operator/results/cmd-20260905-135000-server-health/
?? .github/remote-operator/results/cmd-20260905-135500-disk-space/
?? .github/remote-operator/results/cmd-20260905-140000-server-status-tree/
?? .github/remote-operator/results/cmd-20260905-140500-server-runtime-final/
?? .github/remote-operator/state/cmd-20260904-220309-operator-test.json
?? .github/remote-operator/state/cmd-20260904-220600-home-tree.json
?? .github/remote-operator/state/cmd-20260904-220900-operator-delivery-diagnostic.json
?? .github/remote-operator/state/cmd-20260905-005600-server-status.json
?? .github/remote-operator/state/cmd-20260905-135000-server-health.json
?? .github/remote-operator/state/cmd-20260905-135500-disk-space.json
?? .github/remote-operator/state/cmd-20260905-140000-server-status-tree.json
?? .github/remote-operator/state/cmd-20260905-140500-server-runtime-final.json
?? docs/REMOTE_OPERATOR_UNIVERSAL.md
HEALTH=<html>
<head><title>301 Moved Permanently</title></head>
<body>
<center><h1>301 Moved Permanently</h1></center>
<hr><center>nginx/1.24.0 (Ubuntu)</center>
</body>
</html>

READINESS=<html>
<head><title>301 Moved Permanently</title></head>
<body>
<center><h1>301 Moved Permanently</h1></center>
<hr><center>nginx/1.24.0 (Ubuntu)</center>
</body>
</html>

CONTAINERS=
NAME                           IMAGE                        COMMAND                  SERVICE             CREATED        STATUS                  PORTS
madworld-api-1                 madworld-api                 "uvicorn app.main:ap…"   api                 12 hours ago   Up 12 hours (healthy)   127.0.0.1:8090->8000/tcp
madworld-postgres-1            postgres:16                  "docker-entrypoint.s…"   postgres            12 hours ago   Up 12 hours (healthy)   127.0.0.1:5433->5432/tcp
madworld-world-tick-worker-1   madworld-world-tick-worker   "python -m scripts.w…"   world-tick-worker   12 hours ago   Up 12 hours             8000/tcp
FAILED_UNITS=
OPERATOR=
active
SYNC_TIMER=
active
RUNTIME_FINAL_END
```

## STDERR
```text
```
