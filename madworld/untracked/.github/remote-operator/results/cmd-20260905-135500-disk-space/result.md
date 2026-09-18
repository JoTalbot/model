# Remote Command Result

- **Command ID:** `cmd-20260905-135500-disk-space`
- **Attempt ID:** `cmd-20260905-135500-disk-space-attempt-20260904T223007Z-879086`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T22:30:07Z`
- **Finished:** `2026-09-04T22:30:07Z`
- **Duration:** `0s`

## Command
```bash
set -e; echo DISK_SPACE_START; echo ROOT=$(df -h / | awk 'NR==2{print $4 " free (" $5 " used)"}'); echo MADWORLD=$(df -h /opt/madworld | awk 'NR==2{print $4 " free (" $5 " used)"}'); echo HOME=$(df -h /home/ubuntu | awk 'NR==2{print $4 " free (" $5 " used)"}'); echo DISK_SPACE_OK
```

## STDOUT
```text
DISK_SPACE_START
ROOT=97G free (33% used)
MADWORLD=97G free (33% used)
HOME=97G free (33% used)
DISK_SPACE_OK
```

## STDERR
```text
```
