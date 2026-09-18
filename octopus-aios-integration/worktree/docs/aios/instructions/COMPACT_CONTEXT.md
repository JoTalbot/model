# Octopus Compact Context v9.2 (2026-07-16)

## Canonical Paths
- /mnt/agents/ (legacy /root/agents/)
- Project: ~/agents/-Octopus/

## Skills Status
- Total: 257 IDs, 250 unique names
- Real: 257 (0 stubs) + 10 REAL implementations (2026-07-16)
- Duplicates: 7 (cross-category symlinks/aliases)
- Categories: core=144, memory=34, meta=37, swarm=34, dr=2, mcp=2, research=4

## Infrastructure
- SSH: root@traff.tplinkdns.com:2222
- GitHub: JoTalbot/octopus, runner ubu-worker-octopus ONLINE
- Railway: octopus-production-71fe.up.railway.app
- Docker: 79 containers
- Disk: 75% used (27GB free)
- Swap: 3GB/4GB used, swappiness=10

## Active Skills
- skill-health-monitor (restored via symlink)
- octopus-ollama-proxy (port 11435, 5 models)
- octopus-external-data (7 free APIs, 1h cache)
- autonomous_agent.py (timer active, ~6min cycles)

## Recent Improvements (2026-07-16)
- Fixed 4 broken symlinks in core/ (recreated as real skills)
- Removed 11 duplicate skill directories across memory/swarm/meta
- Added SKILL.md for 9 undocumented skills
- Created run.py + tests for 10 former stubs
- Verified: 0 stubs, 257 real skills


## 10 New REAL Skills (2026-07-16)
- incident-triage: P1-P4 incident classification (systemd+docker+disk+memory)
- config-drift-audit: config checksum drift detection + secret permissions
- disk-growth-forecast: linear regression disk fill prediction (80/90/95%)
- log-summarizer: journalctl+nginx+docker+octopus log summarization
- nginx-route-auditor: server block parsing + proxy availability + security headers
- dependency-risk-audit: pip/npm vulnerability + outdated package scanning
- dead-code-hunter: AST-based unused imports/functions + commented blocks
- cron-safety-audit: crontab+systemd timer safety + conflict detection
- api-smoke-matrix: multi-endpoint health matrix with latency measurement
- backup-gap-analyzer: critical data freshness + IPFS pin + GitHub sync audit

## Constraints
- Free-tier servers only for autonomous scaling
- Hetzner paid instances forbidden without explicit command
- Files are directives read in alphabetical order
