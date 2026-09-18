#!/bin/bash
# Memory/load-guarded T2 hyperopt runner (after 2026-08-16 OOM kills of the plain runner).
#
# Differences vs data/freqtrade/run_hyperopt.sh:
# - before each pair waits for a quiet window: MemAvailable>=2.2G, SwapFree>=300M,
#   load1<=14 (4-core host); rechecks every 3 min, skips pair after 6h of waiting;
# - nice -n 15, single worker (-j 1), 60s cool-down between pairs;
# - identical hyperopt parameters otherwise (300 epochs, SortinoHyperOptLoss,
#   fee 0.0015, timerange 20190720-20260816, spot-only) for comparability.
#
# Usage:  nohup scripts/freqtrade_validation/run_hyperopt_guarded.sh >/dev/null 2>&1 &
# Log:    data/freqtrade/hyperopt_run_guarded.log
set -u
cd /root/AIOS
FB=/root/freqtrade-venv/bin/freqtrade
LOG=/root/AIOS/data/freqtrade/hyperopt_run_guarded.log
SP=/root/AIOS/data/freqtrade/strategies
MIN_AVAIL_MB=2200
MIN_SWAPFREE_MB=300
MAX_LOAD1=14
WAIT_S=180
MAX_WAIT_S=21600

avail_mb()    { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
swapfree_mb() { awk '/SwapFree/    {print int($2/1024)}' /proc/meminfo; }
load1()       { cut -d' ' -f1 /proc/loadavg; }

quiet_window() {
  [ "$(avail_mb)" -ge "$MIN_AVAIL_MB" ] || return 1
  [ "$(swapfree_mb)" -ge "$MIN_SWAPFREE_MB" ] || return 1
  awk -v l="$(load1)" -v m="$MAX_LOAD1" 'BEGIN{exit !(l+0<=m+0)}'
}

for SYM in BTC ETH SOL BNB NEAR; do
  waited=0
  until quiet_window; do
    sleep $WAIT_S; waited=$((waited+WAIT_S))
    if [ "$waited" -ge "$MAX_WAIT_S" ]; then
      echo "=== GUARDED $SYM SKIPPED after ${waited}s ($(date -u)) load=$(load1) avail=$(avail_mb)MB swapfree=$(swapfree_mb)MB ===" >> "$LOG"
      continue 2
    fi
  done
  echo "=== GUARDED HYPEROPT $SYM start $(date -u) avail=$(avail_mb)MB swapfree=$(swapfree_mb)MB load=$(load1) ===" >> "$LOG"
  nice -n 15 "$FB" hyperopt --strategy T2MomentumHyper --strategy-path "$SP" \
    --config "/root/AIOS/data/freqtrade/configs/config_t2_${SYM}.json" \
    --datadir /root/AIOS/data/freqtrade/data \
    --timerange 20190720-20260816 --fee 0.0015 --data-format-ohlcv json \
    --userdir /root/AIOS/data/freqtrade \
    --hyperopt-loss SortinoHyperOptLoss --spaces buy sell --epochs 300 --random-state 42 -j 1 \
    >> "$LOG" 2>&1
  rc=$?
  echo "=== GUARDED HYPEROPT $SYM done rc=$rc $(date -u) ===" >> "$LOG"
  sleep 60
done
echo "GUARDED ALL DONE $(date -u)" >> "$LOG"
