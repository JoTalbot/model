# Octopus — матрица портов (main + AWS)
Обновлено: 2026-05-30 05:05 UTC

## Цель
Единый документ по внешней поверхности, локальным сервисам и туннелям.

---

## MAIN: 178.105.142.113 (Hetzner)

| Порт | Привязка | Доступ | Назначение | Статус |
|---|---|---|---|---|
| 22 | host | public | SSH | оставить |
| 80/443 | nginx | public | web/admin reverse proxy | оставить |
| 8000/udp | host | public | Kademlia / swarm | оставить |
| 9000/udp | host | public | Gossip | оставить |
| 9100 | 127.0.0.1 | local | status/dashboard | закрыт наружу |
| 9500 | 127.0.0.1 | local | Next admin | закрыт наружу |
| 9090 | 127.0.0.1 | local | Prometheus | закрыт наружу |
| 3000 | localhost-only by firewall | local | Grafana | закрыт наружу |
| 3100 | localhost-only by firewall | local | Loki | закрыт наружу |
| 3900 | 127.0.0.1 | local | Garage S3 | закрыт наружу |
| 3901 | host | inter-node | Garage RPC | открыт для peer-mode |
| 3903 | 127.0.0.1 | local | Garage Admin | закрыт наружу |
| 8334 | reverse-proxied | public via nginx | Filestash | оставить |
| 9721 | 127.0.0.1 | local tunnel | AWS exporter -> 9719 | оставить |
| 9722 | 127.0.0.1 | local tunnel | AWS node_exporter -> 9100 | оставить |

---

## AWS: 3.79.192.28 (Free Tier)

| Порт | Привязка | Доступ | Назначение | Статус |
|---|---|---|---|---|
| 22 | host | public | SSH | оставить |
| 3900 | 127.0.0.1 | local | Garage S3 | **ужесточено 2026-05-30** |
| 3901 | host | inter-node allowlist | Garage RPC | **allowlist only main<->AWS с 2026-05-30** |
| 3903 | 127.0.0.1 | local | Garage Admin | **ужесточено 2026-05-30** |
| 4001/tcp+udp | docker | public | IPFS p2p | оставить |
| 5001 | 127.0.0.1 | local+tunnel | IPFS API | **переведён в tunnel-only 2026-05-30** |
| 8080 | 127.0.0.1 | local | IPFS gateway | локально |
| 9100 | 127.0.0.1 | local+tunnel | node_exporter | **переведён в tunnel-only 2026-05-30** |
| 9510 | 127.0.0.1 | local+tunnel | memory receiver | **переведён в tunnel-only 2026-05-30** |
| 9719 | 127.0.0.1 | local | aws exporter | уже tunnel-only |

---

## Активные SSH-туннели main -> AWS

`octopus-aws-tunnel.service`
- `127.0.0.1:9721 -> 127.0.0.1:9719` (aws exporter)
- `127.0.0.1:9722 -> 127.0.0.1:9100` (aws node_exporter)
- `127.0.0.1:9723 -> 127.0.0.1:9510` (aws memory receiver)
- `127.0.0.1:9724 -> 127.0.0.1:5001` (aws IPFS API)

---

## Приоритет следующего ужесточения
1. Решить судьбу `AWS:3901`: либо controlled cluster mode, либо закрытие до preflight.
2. При желании закрыть `AWS:22` по allowlist/VPN.
3. Зафиксировать policy для auxiliary node security group как код/шаблон.
4. Перед включением multi-node Garage согласовать отдельный режим и preflight для `3901`.
