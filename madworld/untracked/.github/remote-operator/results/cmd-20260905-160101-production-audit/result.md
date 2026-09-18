# Remote Command Result

- **Command ID:** `cmd-20260905-160101-production-audit`
- **Attempt ID:** `cmd-20260905-160101-production-audit-attempt-20260904T234850Z-1127120`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T23:48:50Z`
- **Finished:** `2026-09-04T23:48:52Z`
- **Duration:** `2s`

## Command
```bash
set -u
cd /opt/madworld || exit 2
printf '%s\n' 'PRODUCTION_AUDIT_START'
printf 'HOST=%s\n' "$(hostname)"
printf 'NOW=%s\n' "$(date -u +%FT%TZ)"
printf 'GIT_HEAD=%s\n' "$(git rev-parse HEAD 2>/dev/null || echo unknown)"
printf 'ORIGIN_MAIN=%s\n' "$(git rev-parse origin/main 2>/dev/null || echo unknown)"
printf 'GIT_STATUS=%s\n' "$(git status --short --branch 2>/dev/null || echo unknown)"
printf 'DISK=%s\n' "$(df -h /opt/madworld | awk 'NR==2{print $3 "/" $2 "," $4 " free (" $5 ")"}')"
printf 'MEMORY=%s\n' "$(free -h | awk '/Mem:/{print $3 "/" $2 " used, " $7 " available}')"
printf 'BACKUP_TIMER=%s\n' "$(systemctl is-active madworld-backup.timer 2>&1 || true)"
printf 'BACKUP_TIMER_ENABLED=%s\n' "$(systemctl is-enabled madworld-backup.timer 2>&1 || true)"
printf '%s\n' 'BACKUP_SERVICE_STATUS='
systemctl status madworld-backup.service --no-pager -n 20 2>&1 || true
printf '%s\n' 'BACKUP_FILES='
ls -lh /opt/madworld/backups 2>&1 || true
printf '%s\n' 'BACKUP_LATEST=' 
find /opt/madworld/backups -maxdepth 1 -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -10 || true
printf '%s\n' 'DOCKER_PS='
docker compose -f /opt/madworld/docker-compose.yml ps 2>&1 || true
printf '%s\n' 'HEALTH='
curl -sS -L --max-time 10 -w '\nHTTP_STATUS=%{http_code}\n' http://127.0.0.1/health 2>&1 || true
printf '%s\n' 'READINESS='
curl -sS -L --max-time 10 -w '\nHTTP_STATUS=%{http_code}\n' http://127.0.0.1/health/ready 2>&1 || true
printf '%s\n' 'NGINX_TEST_ROOT='
sudo -n nginx -t 2>&1 || true
printf '%s\n' 'PUBLIC_HTTPS='
curl -k -sS -L --max-time 15 -w '\nHTTP_STATUS=%{http_code}\n' https://api.autosklo.org.ua/health/ready 2>&1 || true
printf '%s\n' 'OPERATOR='
systemctl is-active madworld-remote-operator.service 2>&1 || true
printf '%s\n' 'SYNC_TIMER='
systemctl is-active madworld-remote-operator-sync.timer 2>&1 || true
printf '%s\n' 'FAILED_UNITS='
systemctl --failed --no-legend 2>&1 || true
printf '%s\n' 'PRODUCTION_AUDIT_END'
```

## STDOUT
```text
PRODUCTION_AUDIT_START
HOST=arm-server-01
NOW=2026-09-04T23:48:50Z
GIT_HEAD=b66e1ec3afa0d3796e9a5fd4eafb5107d5d9fac5
ORIGIN_MAIN=c2daaf4b47e34f4381132b9f08ff3ee1587b2445
GIT_STATUS=## main...origin/main [behind 38]
 M .github/remote-operator/COMMANDS.txt
 M .github/workflows/backup-dr-verification.yml
 M .github/workflows/deploy-on-push.yml
 M .github/workflows/remote-operator.yml
 M AGENTS.md
 M docs/REMOTE_OPERATOR.md
 M docs/REMOTE_OPERATOR_INSTALL.md
 M ops/remote-operator/executor.sh
 M ops/remote-operator/watcher.sh
?? .github-deployed-sha
?? .github/remote-operator/REQUESTS/
?? .github/remote-operator/results/cmd-20260904-220309-operator-test/
?? .github/remote-operator/results/cmd-20260904-220600-home-tree/
?? .github/remote-operator/results/cmd-20260904-220900-operator-delivery-diagnostic/
?? .github/remote-operator/results/cmd-20260905-005600-server-status/
?? .github/remote-operator/results/cmd-20260905-135000-server-health/
?? .github/remote-operator/results/cmd-20260905-135500-disk-space/
?? .github/remote-operator/results/cmd-20260905-140000-server-status-tree/
?? .github/remote-operator/results/cmd-20260905-140500-server-runtime-final/
?? .github/remote-operator/results/cmd-20260905-141500-production-proxy-check/
?? .github/remote-operator/results/cmd-20260905-143000-nginx-cert-permission-diagnose/
?? .github/remote-operator/results/cmd-20260905-160101-production-audit/
?? .github/remote-operator/state/cmd-20260904-220309-operator-test.json
?? .github/remote-operator/state/cmd-20260904-220600-home-tree.json
?? .github/remote-operator/state/cmd-20260904-220900-operator-delivery-diagnostic.json
?? .github/remote-operator/state/cmd-20260905-005600-server-status.json
?? .github/remote-operator/state/cmd-20260905-135000-server-health.json
?? .github/remote-operator/state/cmd-20260905-135500-disk-space.json
?? .github/remote-operator/state/cmd-20260905-140000-server-status-tree.json
?? .github/remote-operator/state/cmd-20260905-140500-server-runtime-final.json
?? .github/remote-operator/state/cmd-20260905-141500-production-proxy-check.json
?? .github/remote-operator/state/cmd-20260905-143000-nginx-cert-permission-diagnose.json
?? .github/remote-operator/state/cmd-20260905-160101-production-audit.json
?? .github/workflows/remote-operator-postdeploy-verify.yml
?? .github/workflows/remote-operator-reusable.yml
?? .github/workflows/root-runtime-verify.yml
?? docs/REMOTE_OPERATOR_UNIVERSAL.md
DISK=44G/145G,102G free (30%)
MEMORY=
BACKUP_TIMER=active
BACKUP_TIMER_ENABLED=enabled
BACKUP_SERVICE_STATUS=
○ madworld-backup.service - MadWorld daily PostgreSQL backup
     Loaded: loaded (/etc/systemd/system/madworld-backup.service; static)
     Active: inactive (dead) since Fri 2026-09-04 10:38:08 UTC; 13h ago
TriggeredBy: ● madworld-backup.timer
   Main PID: 3656859 (code=exited, status=0/SUCCESS)
        CPU: 278ms

Sep 04 10:38:08 arm-server-01 systemd[1]: Starting madworld-backup.service - MadWorld daily PostgreSQL backup...
Sep 04 10:38:08 arm-server-01 systemd[1]: madworld-backup.service: Deactivated successfully.
Sep 04 10:38:08 arm-server-01 systemd[1]: Finished madworld-backup.service - MadWorld daily PostgreSQL backup.
BACKUP_FILES=
total 15M
-rw-rw-r-- 1 ubuntu ubuntu 1.4K Sep  4 18:17 backup.log
-rw-rw-r-- 1 ubuntu ubuntu    0 Sep  3 18:17 cron.log
-rw------- 1 ubuntu ubuntu 986K Sep  3 22:31 madworld-20260903T223110Z.dump
-rw------- 1 ubuntu ubuntu  119 Sep  3 22:31 madworld-20260903T223110Z.dump.sha256
-rw------- 1 ubuntu ubuntu 1.3M Sep  4 03:16 madworld-20260904T031600Z.dump
-rw------- 1 ubuntu ubuntu  119 Sep  4 03:16 madworld-20260904T031600Z.dump.sha256
-rw------- 1 ubuntu ubuntu 1.7M Sep  4 10:04 madworld-20260904T100456Z.dump
-rw------- 1 ubuntu ubuntu  119 Sep  4 10:04 madworld-20260904T100456Z.dump.sha256
-rw------- 1 ubuntu ubuntu 1.8M Sep  4 10:38 madworld-20260904T103808Z.dump
-rw------- 1 ubuntu ubuntu  119 Sep  4 10:38 madworld-20260904T103808Z.dump.sha256
-rwx------ 1 ubuntu ubuntu 1.3K Sep  3 13:31 madworld_backup.sh
-rw-rw-r-- 1 ubuntu ubuntu 309K Sep  3 11:56 madworld_db_20260903T115622Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 353K Sep  3 12:35 madworld_db_20260903T123512Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 386K Sep  3 13:05 madworld_db_20260903T130506Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 415K Sep  3 13:31 madworld_db_20260903T133113Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 417K Sep  3 13:33 madworld_db_20260903T133307Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 716K Sep  3 18:17 madworld_db_20260903T181701Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 1.1M Sep  4 00:17 madworld_db_20260904T001701Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 1.5M Sep  4 06:17 madworld_db_20260904T061701Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 1.9M Sep  4 12:17 madworld_db_20260904T121701Z.dump
-rw-rw-r-- 1 ubuntu ubuntu 2.2M Sep  4 18:17 madworld_db_20260904T181701Z.dump
BACKUP_LATEST=
1788545824.5096145360 /opt/madworld/backups/backup.log
1788545823.8326089950 /opt/madworld/backups/madworld_db_20260904T181701Z.dump
1788524222.4748904310 /opt/madworld/backups/madworld_db_20260904T121701Z.dump
1788518288.5045660290 /opt/madworld/backups/madworld-20260904T103808Z.dump.sha256
1788518288.4475655200 /opt/madworld/backups/madworld-20260904T103808Z.dump
1788516296.6377177350 /opt/madworld/backups/madworld-20260904T100456Z.dump.sha256
1788516296.5847172630 /opt/madworld/backups/madworld-20260904T100456Z.dump
1788502622.1490196290 /opt/madworld/backups/madworld_db_20260904T061701Z.dump
1788491761.4984163900 /opt/madworld/backups/madworld-20260904T031600Z.dump.sha256
1788491760.9314112810 /opt/madworld/backups/madworld-20260904T031600Z.dump
DOCKER_PS=
NAME                           IMAGE                        COMMAND                  SERVICE             CREATED        STATUS                  PORTS
madworld-api-1                 madworld-api                 "uvicorn app.main:ap…"   api                 13 hours ago   Up 13 hours (healthy)   127.0.0.1:8090->8000/tcp
madworld-postgres-1            postgres:16                  "docker-entrypoint.s…"   postgres            13 hours ago   Up 13 hours (healthy)   127.0.0.1:5433->5432/tcp
madworld-world-tick-worker-1   madworld-world-tick-worker   "python -m scripts.w…"   world-tick-worker   13 hours ago   Up 13 hours             8000/tcp
HEALTH=
curl: (60) SSL certificate problem: self-signed certificate in certificate chain
More details here: https://curl.se/docs/sslcerts.html

curl failed to verify the legitimacy of the server and therefore could not
establish a secure connection to it. To learn more about this situation and
how to fix it, please visit the web page mentioned above.

HTTP_STATUS=301
READINESS=
curl: (60) SSL certificate problem: self-signed certificate in certificate chain
More details here: https://curl.se/docs/sslcerts.html

curl failed to verify the legitimacy of the server and therefore could not
establish a secure connection to it. To learn more about this situation and
how to fix it, please visit the web page mentioned above.

HTTP_STATUS=301
NGINX_TEST_ROOT=
sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
sudo: If sudo is running in a container, you may need to adjust the container configuration to disable the flag.
PUBLIC_HTTPS=
{"status":"ok","service":"madworld-api","database":"ok","migrations_applied":41}
HTTP_STATUS=200
OPERATOR=
active
SYNC_TIMER=
active
FAILED_UNITS=
PRODUCTION_AUDIT_END
```

## STDERR
```text
awk: cmd. line:1: /Mem:/{print $3 "/" $2 " used, " $7 " available}
awk: cmd. line:1:                                     ^ unterminated string
```
