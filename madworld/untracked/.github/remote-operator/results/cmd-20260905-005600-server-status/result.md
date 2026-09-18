# Remote Command Result

- **Command ID:** `cmd-20260905-005600-server-status`
- **Attempt ID:** `cmd-20260905-005600-server-status-attempt-20260904T215956Z-786035`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T21:59:56Z`
- **Finished:** `2026-09-04T21:59:56Z`
- **Duration:** `0s`

## Command
```bash
set -e; echo SERVER_STATUS_START; echo HOST=$(hostname); echo USER=$(id -un); echo UID=$(id -u); echo PWD=$(pwd); echo KERNEL=$(uname -sr); echo ARCH=$(uname -m); echo UPTIME=$(uptime -p); echo LOAD=$(cut -d' ' -f1-3 /proc/loadavg); echo DISK=$(df -h /opt/madworld | awk 'NR==2{print $5 "," $4 " free"}'); echo MEMORY=$(free -h | awk '/Mem:/{print $3 "/" $2 "," $7 " available"}'); echo OPERATOR=$(systemctl is-active madworld-remote-operator.service); echo SYNC_TIMER=$(systemctl is-active madworld-remote-operator-sync.timer); echo FAILED_UNITS=$(systemctl --failed --no-legend | wc -l); echo GIT_HEAD=$(git rev-parse HEAD); echo GIT_MAIN=$(git rev-parse origin/main 2>/dev/null || echo unknown); echo SERVER_STATUS_OK
```

## STDOUT
```text
SERVER_STATUS_START
HOST=arm-server-01
USER=ubuntu
UID=1001
PWD=/opt/madworld
KERNEL=Linux 6.17.0-1018-oracle
ARCH=aarch64
UPTIME=up 3 days, 6 hours, 56 minutes
LOAD=1.27 0.93 1.03
DISK=30%,102G free
MEMORY=10Gi/23Gi,12Gi available
OPERATOR=active
SYNC_TIMER=active
FAILED_UNITS=0
GIT_HEAD=b66e1ec3afa0d3796e9a5fd4eafb5107d5d9fac5
GIT_MAIN=b66e1ec3afa0d3796e9a5fd4eafb5107d5d9fac5
SERVER_STATUS_OK
```

## STDERR
```text
```
