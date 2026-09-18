# System Inventory — Octopus (autosklo-prod)
Обновлено: 2026-05-30 05:05 UTC

## Сервер
- Host: 178.105.142.113 (Hetzner CX33, Nuremberg)
- OS: Ubuntu 22.04 LTS
- CPU: 4 vCPU
- RAM: 7.6GB
- Disk: 38GB SSD

## Docker Containers (15)
| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| octopus | octopus-current | 8000(swarm),8080(api),9100(dashboard) | Main swarm node |
| octopus-child-8300..8305 | octopus-current | 8300-8305(swarm),9400-9410(control) | 6 child nodes |
| octopus-next-admin | octopus-next-admin | 9500 | Next.js admin UI |
| filestash | machines/filestash | 8334 | Web file manager |
| ipfs-node | ipfs/kubo | 4001(p2p),5001(api),8180(gw) | IPFS node |
| octopus-prometheus | prom/prometheus | 9090 | Metrics |
| octopus-grafana | grafana/grafana | 3000 | Dashboards |
| octopus-blackbox | prom/blackbox-exporter | 9115 | HTTP probing |
| octopus-loki | grafana/loki | 3100 | Log aggregation |
| octopus-promtail | grafana/promtail | 9080 | Log shipping |

## Systemd Services (key)
| Service | Type | Purpose |
|---------|------|---------|
| octopus.service | always | Main swarm node |
| octopus-child@83XX | always | Child swarm nodes |
| octopus-next-admin | always | Admin UI |
| garage.service | always | S3 object storage |
| juicefs-swarm.service | always | Distributed filesystem |
| octopus-alerting | always | Monitoring + TG alerts |
| octopus-watchdog | always | External node watchdog |
| octopus-tg-bot | always | Telegram bot |
| octopus-alerts-tg | always | Prometheus→TG bridge |
| octopus-aws-tunnel | always | SSH tunnel to AWS |
| autosklo.service | always | AutoSklo web app |

## Timers (25)
backup, s3-mirror, db-cleanup, smoke, ipfs-gc, ocr-worker, 
vfs-ocr-worker, http-replicator, ipfs-pin-coordinator, 
memory-replicator, memory-gc-dryrun, memory-indexer, 
memory-restore-drill, memory-restore-alert, loki-alert-relay,
archive-rotate, autoscale-local, local-backup, local-s3-backup,
pg-vacuum, prom-targets, s3-backup, sync-control-ports, tg-registry-report, env-validate

## External Nodes
| Node | IP | Services | Notes |
|------|-----|----------|-------|
| AWS EU | 3.79.192.28 | IPFS(p2p public, API tunnel-only), memory-receiver(tunnel-only), node-exporter(tunnel-only), Garage(RPC allowlist, S3/Admin local) | Free Tier t2.micro |

## Databases
| DB | Size | Engine | Purpose |
|----|------|--------|---------|
| app_db | ~197MB | PostgreSQL 16 | Main octopus data |
| autosklo_db | ~9.5MB | PostgreSQL 16 | AutoSklo app |
| octopus_db | ~8.6MB | PostgreSQL 16 | JuiceFS metadata |

## Key Paths
| Path | Size | Purpose |
|------|------|---------|
| /opt/octopus | 671MB | Swarm source code |
| /opt/octopus-next-admin | ~1.1GB | Admin UI (Next.js) |
| /opt/autosklo | 421MB | AutoSklo app |
| /opt/ipfs_data | 687MB | IPFS repo |
| /var/lib/octopus | 94MB | State, memory pool, registry |
| /var/lib/garage | 9.7MB | Garage S3 metadata |
| /var/backups/octopus | 100MB | Daily backups |
| /mnt/swarm | 1PB virtual | JuiceFS distributed disk |
| /mnt/memory | - | Filestash unified view |
| /root/agents | 3.3MB | Agent instructions/logs |
