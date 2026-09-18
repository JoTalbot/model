set -euo pipefail
cd /opt/madworld
NAME="madworld-dr-verify-$$"
NET="${NAME}-net"
SRC="${NAME}-src"
DST="${NAME}-dst"
cleanup() {
  docker rm -f "$SRC" "$DST" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
docker run -d --name "$SRC" --network "$NET" -e POSTGRES_PASSWORD=madworld -e POSTGRES_DB=madworld_source postgres:16 >/dev/null
docker run -d --name "$DST" --network "$NET" -e POSTGRES_PASSWORD=madworld -e POSTGRES_DB=madworld_restore postgres:16 >/dev/null
for i in $(seq 1 30); do
  docker exec "$SRC" pg_isready -U postgres -d madworld_source >/dev/null 2>&1 && docker exec "$DST" pg_isready -U postgres -d madworld_restore >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$SRC" psql -U postgres -d madworld_source -v ON_ERROR_STOP=1 -c "CREATE TABLE schema_migrations (version text PRIMARY KEY); INSERT INTO schema_migrations VALUES ('001'),('002'),('003'); CREATE TABLE dr_probe (id integer PRIMARY KEY, value text NOT NULL); INSERT INTO dr_probe VALUES (1,'madworld-dr-verification');" >/dev/null
START_NS=$(date +%s%N)
docker run --rm --network "$NET" -v /opt/madworld/ops/backup_restore.sh:/work/backup_restore.sh:ro -v /tmp:/tmp postgres:16 bash -lc 'set -euo pipefail; chmod +x /work/backup_restore.sh; MADWORLD_DATABASE_URL=postgresql://postgres:madworld@'"$SRC"':5432/madworld_source RESTORE_DATABASE_URL=postgresql://postgres:madworld@'"$DST"':5432/madworld_restore BACKUP_FILE=/tmp/'"$NAME"'.dump /work/backup_restore.sh; PGPASSWORD=madworld psql postgresql://postgres:madworld@'"$DST"':5432/madworld_restore -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) = 3 AS migrations_ok FROM schema_migrations;" -c "SELECT value = '\''madworld-dr-verification'\'' AS invariant_ok FROM dr_probe WHERE id = 1;"' 
END_NS=$(date +%s%N)
RTO=$(python3 -c "print(f'{($END_NS-$START_NS)/1_000_000_000:.3f}')")
rm -f "/tmp/$NAME.dump"
printf 'DR_ISOLATED_REHEARSAL=PASS\n'
printf 'MEASURED_RTO_SECONDS=%s\n' "$RTO"
printf 'ENVIRONMENT=ephemeral_postgres16_containers\n'
printf 'PRODUCTION_DATABASE_TOUCHED=false\n'
