#!/usr/bin/env bash
set -euo pipefail

# Safe rollback rehearsal: never changes the live MadWorld deployment.
# It builds the documented known-good candidate in an isolated Docker network,
# migrates a disposable PostgreSQL database, verifies API health, then destroys
# all rehearsal resources.
TARGET_COMMIT="${ROLLBACK_TARGET_COMMIT:-44df14000195d32b1472f96a2a6aa6d3dc31b5ee}"
BASE_DIR="$(git rev-parse --show-toplevel)"
NAME="madworld-rollback-rehearsal-${RANDOM}-$$"
NET="${NAME}_net"
DB="${NAME}_db"
API="${NAME}_api"
IMAGE="${NAME}_backend"
WT="$(mktemp -d /tmp/madworld-rollback-XXXXXX)"

cleanup() {
  set +e
  docker rm -f "$API" "$DB" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker image rm "$IMAGE" >/dev/null 2>&1 || true
  git -C "$BASE_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$WT"
}
trap cleanup EXIT

echo "ROLLBACK_REHEARSAL_START"
echo "TARGET_COMMIT=$TARGET_COMMIT"
echo "PRODUCTION_DATABASE_TOUCHED=false"

git -C "$BASE_DIR" fetch --quiet origin main
git -C "$BASE_DIR" worktree add --detach "$WT" "$TARGET_COMMIT"

test "$(git -C "$WT" rev-parse HEAD)" = "$TARGET_COMMIT"

docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" \
  -e POSTGRES_USER=madworld -e POSTGRES_PASSWORD=madworld -e POSTGRES_DB=madworld \
  postgres:16 >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$DB" pg_isready -U madworld -d madworld >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$DB" pg_isready -U madworld -d madworld >/dev/null

docker build -q -t "$IMAGE" -f "$WT/ops/Dockerfile.backend" "$WT" >/dev/null

docker run --rm --network "$NET" \
  -e MADWORLD_DATABASE_URL=postgresql://madworld:madworld@${DB}:5432/madworld \
  "$IMAGE" python scripts/migrate.py

docker run -d --name "$API" --network "$NET" \
  -e MADWORLD_DATABASE_URL=postgresql://madworld:madworld@${DB}:5432/madworld \
  "$IMAGE" uvicorn app.main:app --host 0.0.0.0 --port 8000 >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$API" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$API" python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())"
docker exec "$API" python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).read().decode())"

echo "ROLLBACK_TARGET_VERIFIED=true"
echo "ISOLATED_API_HEALTH=PASS"
echo "ISOLATED_DB_MIGRATION=PASS"
echo "PRODUCTION_DATABASE_TOUCHED=false"
echo "ROLLBACK_REHEARSAL_PASS=true"
e