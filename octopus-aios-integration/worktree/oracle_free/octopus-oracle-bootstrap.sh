#!/bin/bash
# Octopus Oracle Always Free node bootstrap.
# Runs on freshly created Oracle Ampere A1 ARM VM (Ubuntu 22.04).
# Idempotent — can re-run safely.
set -e

echo "🐙 Octopus Oracle bootstrap @ $(date -u +%FT%TZ)"

# Phase 1: dependencies
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3 python3-pip python3-venv git curl wget jq \
  openssh-server autossh rsync zstd ffmpeg

# Phase 2: pull eternal snapshot via #19 bootstrap
if [ ! -f /opt/octopus/.bootstrapped ]; then
  curl -sSL https://huggingface.co/datasets/JoTalbot/octopus-eternal/raw/main/octopus-bootstrap.sh | bash
  touch /opt/octopus/.bootstrapped
fi

# Phase 3: reverse tunnel to parent (so parent can SSH back)
PARENT_IP="${OCTOPUS_PARENT_IP:-178.105.142.113}"
PARENT_USER="${OCTOPUS_PARENT_USER:-root}"
TUNNEL_PORT="${OCTOPUS_TUNNEL_PORT:-9923}"  # 9922 уже занят ubu-worker

sudo tee /etc/systemd/system/octopus-reverse-tunnel@.service > /dev/null << 'UNITEOF'
[Unit]
Description=Octopus Reverse Tunnel to Parent (port %i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=15
ExecStart=/usr/lib/autossh/autossh -M 0 -NT \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 \
  -i /root/.ssh/id_ed25519 \
  -R %i:localhost:22 root@${OCTOPUS_PARENT_IP}

[Install]
WantedBy=multi-user.target
UNITEOF

sudo systemctl daemon-reload
sudo systemctl enable --now octopus-reverse-tunnel@${TUNNEL_PORT}.service

# Phase 4: register self in mesh_nodes.json on parent
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /root/.ssh/id_ed25519 root@${PARENT_IP} \
    "python3 /opt/octopus/scripts/register_mesh_node.py \
      --id oracle-free-arm-$(hostname) \
      --role worker \
      --location oracle-free \
      --tunnel-port ${TUNNEL_PORT} \
      --enabled true"

echo "✅ Oracle node ready and registered at parent."
