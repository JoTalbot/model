#!/usr/bin/env bash
# export.sh — пересоздаёт снимок репозитория model с хоста arm-server-01.
# Требуется: SSH-доступ (ssh ubuntu@HOST) и путь HOST в переменной HOST или $1.
#
# Никакие секреты не копируются: ключи живут в env хоста, а не в файлах.
# Перед пушем прогнать:  grep -rniE 'ghp_|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE' .
set -euo pipefail
HOST="${1:-${HOST:-}}"
[ -n "$HOST" ] || { echo "usage: $0 <ssh-host>  (или HOST=ip ./export.sh)"; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

ssh "$HOST" "bash -s" <<'REMOTE' > /dev/null
set -eu
STAGE=/tmp/model-content
rm -rf "$STAGE"; mkdir -p "$STAGE"/config/hermes "$STAGE"/code/llm "$STAGE"/code/model-watch "$STAGE"/patches "$STAGE"/inventory
cp -a /opt/hermes/config/. "$STAGE"/config/hermes/
find "$STAGE"/config/hermes -name '*.bak*' -delete
A=/opt/aios
for f in llm/llm_balancer.py llm/dynamic_router_autotuner.py llm/__init__.py \
         consensus/multi_agent_debate.py evolution/auto_evolution_engine.py \
         governance/github_pr_reviewer.py memory_fabric/knowledge_graph.py \
         cognition/vision_pipeline.py \
         tools/cluster_health.py tools/cpu_throttle_guard.py \
         tools/network_latency_probe.py tools/registry.json; do
  [ -f "$A/$f" ] && { mkdir -p "$STAGE/code/llm/$(dirname "$f")"; cp "$A/$f" "$STAGE/code/llm/$f"; }
done
[ -d "$A/automation" ] && find "$A/automation" -type f \( -name '*.py' -o -name '*.json' -o -name '*.md' -o -name '*.yaml' -o -name '*.yml' -o -name '*.sh' \) -size -200k \
   | while read f; do d="$STAGE/code/llm/automation/$(dirname "${f#$A/automation/}")"; mkdir -p "$d"; cp "$f" "$d/"; done
cp /opt/orchestrator/arena_service/model_watch.py "$STAGE"/code/model-watch/
cp /opt/orchestrator/arena_service/arena-model-watch.service "$STAGE"/code/model-watch/ 2>/dev/null || true
cp /opt/orchestrator/arena_service/arena-model-watch.timer  "$STAGE"/code/model-watch/ 2>/dev/null || true
for d in /opt/words /opt/orchestrator /opt/aios /opt/madworld /opt/octopus-browser /opt/logistics; do
  n=$(basename "$d"); [ -d "$d/.git" ] || continue
  (cd "$d" && git diff -- . 2>/dev/null) > "$STAGE/patches/$n.diff"
  [ -s "$STAGE/patches/$n.diff" ] || rm -f "$STAGE/patches/$n.diff"
done
tar -czf /tmp/model-content.tar.gz -C "$STAGE" .
REMOTE

OUT="$STAGE.out"; mkdir -p "$OUT"
scp -q "$HOST":/tmp/model-content.tar.gz "$STAGE/src.tar.gz"
tar -xzf "$STAGE/src.tar.gz" -C "$OUT"
find "$OUT" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.pyc' -delete 2>/dev/null || true

echo "Snapshot rebuilt in $OUT — review, then copy over repo root and commit."
