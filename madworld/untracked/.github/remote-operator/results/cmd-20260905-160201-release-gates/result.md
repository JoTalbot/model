# Remote Command Result

- **Command ID:** `cmd-20260905-160201-release-gates`
- **Attempt ID:** `cmd-20260905-160201-release-gates-attempt-20260904T235024Z-1133576`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T23:50:24Z`
- **Finished:** `2026-09-04T23:50:25Z`
- **Duration:** `1s`

## Command
```bash
set -u
cd /opt/madworld || exit 2
printf '%s\n' 'RELEASE_GATES_START'
printf 'HOST=%s\n' "$(hostname)"
printf 'NOW=%s\n' "$(date -u +%FT%TZ)"
printf '%s\n' 'BACKUP_VERIFY='
LATEST=$(find /opt/madworld/backups -maxdepth 1 -type f -name 'madworld-*.dump' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
if [ -n "$LATEST" ] && [ -f "${LATEST}.sha256" ]; then sha256sum -c "${LATEST}.sha256" 2>&1; printf 'LATEST_BACKUP=%s\n' "$LATEST"; else printf '%s\n' 'BACKUP_CHECK=UNVERIFIED'; fi
printf '%s\n' 'BACKUP_TIMER='
systemctl is-active madworld-backup.timer 2>&1 || true
systemctl is-enabled madworld-backup.timer 2>&1 || true
systemctl list-timers --all --no-legend madworld-backup.timer 2>&1 || true
printf '%s\n' 'DR_CAPABILITY='
printf 'BACKUP_RESTORE_SCRIPT=%s\n' "$(test -x ops/backup_restore.sh && echo present || echo missing)"
printf 'DR_ENV_MADWORLD_DATABASE_URL=%s\n' "$(test -n "${MADWORLD_DATABASE_URL:-}" && echo present || echo absent)"
printf 'DR_ENV_RESTORE_DATABASE_URL=%s\n' "$(test -n "${RESTORE_DATABASE_URL:-}" && echo present || echo absent)"
printf '%s\n' 'CAPACITY_ENVIRONMENT='
find /opt/madworld -maxdepth 2 -type f \( -iname '*capacity*' -o -iname '*load*' -o -iname '*stress*' \) -printf '%p\n' 2>/dev/null | sort | head -100
printf '%s\n' 'ANDROID_DEVICES='
if command -v adb >/dev/null 2>&1; then adb version 2>&1; adb devices -l 2>&1; else echo 'adb=absent'; fi
if command -v emulator >/dev/null 2>&1; then emulator -list-avds 2>&1; else echo 'emulator=absent'; fi
printf '%s\n' 'ANDROID_SDK=' 
find /home/ubuntu/Android/Sdk/platforms -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort -V || true
printf '%s\n' 'PUBLIC_TLS=' 
printf '' | openssl s_client -connect api.autosklo.org.ua:443 -servername api.autosklo.org.ua -verify_return_error 2>&1 | awk '/Verify return code|subject=|issuer=/{print}' || true
printf '%s\n' 'PUBLIC_READY=' 
curl -sS -L --max-time 15 -w '\nHTTP_STATUS=%{http_code}\n' https://api.autosklo.org.ua/health/ready 2>&1 || true
printf '%s\n' 'FAILED_UNITS='
systemctl --failed --no-legend 2>&1 || true
printf '%s\n' 'RELEASE_GATES_END'
```

## STDOUT
```text
RELEASE_GATES_START
HOST=arm-server-01
NOW=2026-09-04T23:50:24Z
BACKUP_VERIFY=
/opt/madworld/backups/madworld-20260904T103808Z.dump: OK
LATEST_BACKUP=/opt/madworld/backups/madworld-20260904T103808Z.dump
BACKUP_TIMER=
active
enabled
Sat 2026-09-05 03:18:51 UTC 3h 28min Fri 2026-09-04 03:16:00 UTC 20h ago madworld-backup.timer madworld-backup.service
DR_CAPABILITY=
BACKUP_RESTORE_SCRIPT=missing
DR_ENV_MADWORLD_DATABASE_URL=absent
DR_ENV_RESTORE_DATABASE_URL=absent
CAPACITY_ENVIRONMENT=
/opt/madworld/ops/B10_CAPACITY_CI_EVIDENCE.md
/opt/madworld/ops/B10_CAPACITY_VERIFICATION.md
/opt/madworld/ops/LOAD_TEST_PLAN.md
ANDROID_DEVICES=
adb=absent
emulator=absent
ANDROID_SDK=
PUBLIC_TLS=
subject=CN = autosklo.org.ua
issuer=C = US, O = Google Trust Services, CN = WE1
Verify return code: 0 (ok)
PUBLIC_READY=
{"status":"ok","service":"madworld-api","database":"ok","migrations_applied":41}
HTTP_STATUS=200
FAILED_UNITS=
RELEASE_GATES_END
```

## STDERR
```text
```
