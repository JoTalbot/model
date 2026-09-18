set -u
# Phase 1 of ops/B10_CAPACITY_VERIFICATION.md: bounded, read-only, low-volume baseline.
# 20 sequential + 5x4 concurrent GETs against /health and /health/ready only. No writes.
# This is NOT the isolated capacity test and does not close the capacity gate.
printf '%s\n' 'CAPACITY_BASELINE_START'
printf 'HOST=%s NOW=%s\n' "$(hostname)" "$(date -u +%FT%TZ)"
printf '%s\n' 'BEFORE_LOAD='; uptime; free -m | head -2
printf '%s\n' 'SEQUENTIAL_20='
for i in $(seq 1 20); do curl -o /dev/null -sS -w '%{http_code} %{time_total}\n' --max-time 10 http://127.0.0.1/health/ready || true; done | sort | uniq -c | sort -rn | head -5
printf '%s\n' 'CONCURRENT_5x4='
for r in 1 2 3 4; do for c in 1 2 3 4 5; do curl -o /dev/null -sS -w '%{http_code} %{time_total}\n' --max-time 10 http://127.0.0.1/health & done; wait; done 2>&1 | awk '{codes[$1]++; t+=$2; n++; if($2>max)max=$2} END {for(c in codes) printf "code=%s count=%d\n", c, codes[c]; if(n) printf "avg=%.4f max=%.4f n=%d\n", t/n, max, n}'
printf '%s\n' 'AFTER_LOAD='; uptime; free -m | head -2
printf '%s\n' 'PG_CONNECTIONS='; docker compose -f /opt/madworld/docker-compose.yml exec -T postgres psql -U "${POSTGRES_USER:-madworld}" -d "${POSTGRES_DB:-madworld}" -tAc 'select count(*) from pg_stat_activity' 2>&1 || true
printf '%s\n' 'API_LOG_ERRORS_LAST_5M='; docker compose -f /opt/madworld/docker-compose.yml logs --since 5m api 2>&1 | grep -ciE 'error|traceback' || true
printf '%s\n' 'CAPACITY_BASELINE_END'
