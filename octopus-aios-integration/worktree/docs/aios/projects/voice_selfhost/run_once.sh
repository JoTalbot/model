#!/usr/bin/env bash
set -euo pipefail
TARGET_DIR=${OCTOPUS_VOICE_TARGET_DIR:-/mnt/swarm/google_drive_calls/Calls}
CLUSTER_THRESHOLD=${CLUSTER_THRESHOLD:-0.75}
exec /opt/octopus-ingest-venv/bin/python /opt/octopus/voice_selfhost/octopus_voice_selfhost.py \
  --target-dir "$TARGET_DIR" \
  --cluster-threshold "$CLUSTER_THRESHOLD" \
  "$@"
