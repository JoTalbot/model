# Remote Command Result

- **Command ID:** `cmd-20260905-135000-server-health`
- **Attempt ID:** `cmd-20260905-135000-server-health-attempt-20260904T215752Z-780061`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T21:57:52Z`
- **Finished:** `2026-09-04T21:57:52Z`
- **Duration:** `0s`

## Command
```bash
set -e; echo SERVER_HEALTH_START; echo HOST=$(hostname); echo USER=$(id -un); echo UID=$(id -u); echo PWD=$(pwd); echo KERNEL=$(uname -sr); echo ARCH=$(uname -m); echo UPTIME=$(uptime -p); echo DISK=$(df -h /opt/madworld | awk 'NR==2{print $5 "," $4 " free"}'); echo MEMORY=$(free -h | awk '/Mem:/{print $7 " available"}'); echo OPERATOR=$(systemctl is-active madworld-remote-operator.service); echo OPERATOR_ENABLED=$(systemctl is-enabled madworld-remote-operator.service); echo SYNC_TIMER=$(systemctl is-active madworld-remote-operator-sync.timer); echo SYNC_ENABLED=$(systemctl is-enabled madworld-remote-operator-sync.timer); echo FAILED_UNITS=$(systemctl --failed --no-legend | wc -l); echo SERVER_HEALTH_OK
```

## STDOUT
```text
SERVER_HEALTH_START
HOST=arm-server-01
USER=ubuntu
UID=1001
PWD=/opt/madworld
KERNEL=Linux 6.17.0-1018-oracle
ARCH=aarch64
UPTIME=up 3 days, 6 hours, 54 minutes
DISK=30%,102G free
MEMORY=12Gi available
OPERATOR=active
OPERATOR_ENABLED=enabled
SYNC_TIMER=active
SYNC_ENABLED=enabled
FAILED_UNITS=0
SERVER_HEALTH_OK
```

## STDERR
```text
```
