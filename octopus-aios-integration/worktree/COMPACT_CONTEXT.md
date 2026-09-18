# COMPACT_CONTEXT.md — Octopus (v9.0 — Batch #100 MILESTONE)
Обновлено: 2026-06-20 13:19 UTC

## 🏆 MILESTONE: 100 батчей выполнено (Batch #92-100)
Grade: S | SLO: green 14/14 | Coverage: 1.0 | NRestarts: 0 | Disk: 84%

## Инфраструктура (total=116 active=116)
| Нода | Доступ | Ресурсы | Статус |
|---|---|---|---|
| parent | 178.105.142.113 | 8GB/38GB | ✅ MAIN |
| ubu-worker | tunnel :9922 | 11GB/109GB | ✅ 72 Docker |
| Railway | octopus-production-71fe.up.railway.app | 512MB | ✅ checking |
| aws-us-east-1 | 54.145.228.26 | t2.micro | ✅ free (умирает) |
| ubu-child 8410-8434 | Docker ubu | 150-256MB x25 | ✅ |
| parent-child 8300-8313 | Docker parent | 200MB x9 | ✅ |
| IPFS-ubu | Docker ubu :4002 | 512MB | ✅ P2P |

## Ключевые сервисы
- octopus :8000 | CAS :9540 | RAG :9560 (7b) | Ingest :9561
- ollama-proxy :11435 → ubu:11434 (qwen2.5:7b/3b/1.5b, nomic-embed)
- whisper-proxy :9581 | metrics-proxy :9923 (node_exporter)
- IPFS :5001 + subscriber + pubsub P2P (15min)
- parent→ubu sync 10min | octopus-railway-watchdog 5min
- GitHub runner: ubu-worker-octopus ONLINE

## GitHub (JoTalbot/octopus)
- Runner: ubu-worker-octopus ONLINE
- Workflows (5): health(15m), sync(6h), backup(3am), test(4h), railway-monitor(10m)
- Token: /root/.gh_token | Railway token: /root/.railway_token
- Secrets: PARENT_SSH_HOST, OCTOPUS_API_URL, OLLAMA_PROXY_URL, RAILWAY_TOKEN

## Railway
- URL: https://octopus-production-71fe.up.railway.app
- Project: octopus-node-1 (84619dda) | Service: octopus (18397fe8)
- Watchdog: octopus-railway-watchdog.timer (5min)
- Лимит: 1 сервис free → +карта = 5+ нод

## Память (БЕССМЕРТНАЯ)
- Packstore: 20425 objects, Coverage 1.0, 23 packs
- IPFS pins: COMPACT_CONTEXT + nodes.json + experience (ipfs_pins.jsonl)
- ubu IPFS: P2P peer с parent
- GitHub: agents/COMPACT_CONTEXT.md + config/nodes.json (auto-sync 6h)
- Offline snapshot: еженедельно (tar.zst)

## LLM Stack
- qwen2.5:7b (heavy), 3b (default), 1.5b (fast) — ubu/proxy :11435
- llama3.2:1b, nomic-embed-text
- Whisper: small/medium на ubu

## Автономные задачи
- 5min: Railway watchdog
- 10min: parent→ubu sync | Railway monitor (GitHub)
- 15min: health-check (GitHub) | IPFS publish (cron)
- 30min: reset-failed (cron)
- 4h: integration tests (GitHub)
- 6h: memory sync + COMPACT_CONTEXT→GitHub (cron+GitHub)
- daily 3am: backup + IPFS pin (GitHub)
- weekly: offline snapshot

## AWS (умирает — 6 долг, карты нет)
- Жива: us-east-1 t2.micro | AMI снимки созданы
- При блокировке: /opt/octopus-aws-shutdown-plan.sh

- [x] Интеграция Persistent Terminal Manager (идеи из архива JoTalbot)
## Следующие шаги (Фаза 2)
- [ ] Oracle Always Free / GCP e2-micro (ждём аккаунты)
- [ ] Railway карта → 5 нод вместо 1
- [ ] Whisper large (нужно 10GB RAM)
- [ ] 200+ нод (цель Фаза 2)

## Команды
- octopus status/health/test/score/backup
- curl https://octopus-production-71fe.up.railway.app/health
- ssh -p 9922 root@localhost | curl http://localhost:11435/api/tags
- python3 /opt/octopus-rag-enhanced.py "query [--heavy]"
- /opt/octopus-aws-shutdown-plan.sh

## Batch #101 (2026-06-20 13:26 UTC)
- NRestarts fixed, disk dedup (hardlink node_modules)
- Whisper medium/small test на ubu
- IPFS P2P parent ↔ ubu (swarm connect)
- COMPACT_CONTEXT pinned на ubu IPFS
- README.md обновлён (42 nodes, Railway online)
- Docker optimize, skill evolution x15
- total=116 active=116 | Docker ubu: 72 | Disk: 84%

## Batch #102 (2026-06-20 13:34 UTC)
- Disk: 84% (cleaned ingest-venv cache, next-admin .next)
- NRestarts: fixed
- GitHub Actions SSH: ubu→parent key authorized
- RAG: reindex triggered
- IPFS: 42 total pins (pack files + nodes + COMPACT_CONTEXT)
- CF Tunnel: ollama + CAS API tunnels
- Grafana: Prometheus datasource configured
- ubu: +10 child (8435-8444), total Docker: 72
- VoxRAG: /opt/octopus-voxrag.py (audio embeddings pipeline)

## R337-R346 update (2026-06-21T10:01:03Z)
- GraphRAG API /metrics added: octopus_graphrag_docs, octopus_graphrag_edges.
- Prometheus scrapes graphrag_api and has basic alert rules.
- octopus automation-json added; MCP read-only tool automation_status_json added.
- workflow automation_json added.
- Disk remains 79%, octopus test 16/16, NRestarts=0.

## [Вектор САМООБЕСПЕЧЕНИЕ архивирован 2026-08-25 по команде владельца — см. /mnt/agents/-Octopus/archive/vector_self_sustain_removed_2026-08-25/]

## МЕНЯТЬСЯ (adapt) — fixed (обновление 2026-07-09 12:51 UTC)
- Вектор МЕНЯТЬСЯ: 450/red → 950/green. telegram_guard ok=True, critical=[].
- Диагноз: critical был от чужих Traff-юнитов на shared-сервере (traff-telegram-alert-service, traff-tg-control-bot, traff-cert-watchdog.timer), ошибочно считавшихся Octopus-дрейфом.
- Фикс telegram_drift_guard.py: + foreign-project классификация для systemd-юнитов (префиксы traff-/autosklo-) и /opt/traff/ файлов. Чужие компоненты видимы (foreign_project_units), но не critical.
- Бонус: УПРОЩАТЬ 920→950. avg 843/B → 902/A. 8/9 векторов green.
- Остался yellow: ЖИТЬ (760, 1 failed/restarting сервис — отдельная health-проблема).

## 2026-08-25 (Arena.ai Agent Mode) — health-fix сессия
- Prometheus восстановлен (apt 2.31.2, prometheus.yml починен, 29 targets). 
- octopus-cas-credential-guard: скан ускорен с часов до 0.5s (исключены тяжёлые папки).
- browser-vision-mcp / browser-vision сервисы отключены (код утерян).
- Лог-спам нод (Gossip peer added, ~350MB/день) — исправлен в исходнике, ждёт пересборки образа octopus-current.
- Диск: 89%→88% (4.7G свободно). Git: 47 коммитов ahead, push заблокирован (токен невалиден, ключ octopus_key не имеет доступа к JoTalbot/octopus).

## 2026-08-25 — полный аудит (Arena.ai Agent Mode, продолжение)
### Безопасность (P0)
- OpenRouter-ключи (2 шт.) — только в /etc/octopus/config.yaml (chmod 600), в git НЕ попадали. Рекомендация: ротация.
- .gitignore усилен (*.bak, *.bak.*); удалён бэкап octopus-swarm-autoheal.py.bak.* с TG-токеном из рабочей папки.
- Удалён мёртвый swarm-сервис octopus_observe_prometheus (битый bind-путь, блокировал 9090). apt-Prometheus: 29 targets.
- session/agent_* ветки с SSH-ключами удалены с GitHub (7 шт). TG-токен в origin/main (api/gemini_hack.py) — по решению владельца не трогаем.
### Тесты (P1)
- 1054 passed, 2 skipped, 0 failed (было 24 failed).
- Адаптированы к текущему API: test_router (13), test_vector_store (13), test_handshake (15), test_phase3 (28), test_control_plane.
- Фиксы кода: router.py (usage_snapshot + calls_per_model/errors_per_model/model_aliases, close(), ValueError при пустых моделях, сообщение All models failed), handshake.py (reason no_hello/clock_skew, pending_shakes в stats), web_endpoints.py (auth-гейт для перехватываемых путей, 503 no container, 400 invalid JSON), vector_store.py (rebuild_tfidf, PersistentVectorIndex.encode).
- router/handshake/web_endpoints монтируются в контейнеры (live-патчи) — ноды перезапущены.
- Git: ветка prod-main-2026-08-25 → 05207e8 (запушено).
### Открыто
- traff-admin/traff-next-panel — auto-restart (битые пути, чужой проект).
- aios-tunnel, octopus-ubu-ollama-tunnel, octopus-next-admin, octopus-critical-guard — диагностика в процессе.

## 2026-08-25 — Итоги сессии (диск, рой, Railway, векторы, git)
### Диск и хранилище
- Диск: 89% → 78% (8.1G свободно). Освобождено ~3.9G: очищен /mnt/swarm/.trash (8.9G, отработанные eternal-снапшоты — публикуются в HF/S3) + juicefs gc (768 слайсов). Garage: 6.2G → 2.1G, resync queue 0.
- Garage v1.1.0 (бакеты swarm-fs → JuiceFS /mnt/swarm, octopus-memory), juicefs-swarm.service active, /mnt/swarm смонтирован.
### Рой
- Локальный рой: parent + 12 детей = 13 нод (8300-8311, +6 новых). Все active, зарегистрированы в parent (handshake + gossip).
- Память: 3.3-3.4G available; каждый child ~45MB.
- Prometheus: 29 targets, 12 up.
### Railway — ПОТЕРЯН
- Проект удалён на аккаунте (projects=0, токен валиден, jo.talbot@gmail.com). Триал истёк — восстановление платное (только по команде). Watchdog переведён на RAILWAY_TOKEN из secrets.env (№51). Нода railway-rw1 не существует.
### Вектор САМООБЕСПЕЧЕНИЕ — АРХИВИРОВАН (команда владельца)
- Скилл money-earner-orchestrator (4MB) + инструкция №46 → /mnt/agents/-Octopus/archive/vector_self_sustain_removed_2026-08-25/.
- Индексы скиллов: 241 skill (пересобраны), skills_health 235. Инструкции 33/53/54 — пометки. consent-gate-enforcer сохранён (гейт present=false).
### Git (JoTalbot/octopus)
- НАШ срез: prod-main-2026-08-25 = 05207e8 (запушен). Локальная main синхронизирована до 05207e8.
- origin/main — ЧУЖОЙ срез (40 чужих коммитов, нет общего предка, 3925 файлов разницы; содержит api/gemini_hack.py с TG-токеном). Ведётся другой сессией, НЕ трогаем.
- Session-ветки с SSH-ключами удалены с GitHub (7 шт). TG-токен не ротируем (решение владельца).
- Тесты: 1054 passed / 2 skipped / 0 failed.

## Память 2026-08-25 — аудит и фиксы
- РАБОТАЕТ: запись (scratch+PG), RAG-поиск, S3-vault (21567 объектов), eternal-снапшот ежечасно (HF+TG+S3, 3.1GB/66 чанков), packstore.
- ВОССТАНОВЛЕНО: PostgreSQL-адаптер (scratch_root→postgres://octopus_user@octopus_db, octopus_artifacts растёт); опыт (315 файлов из archive → experience/, индекс 491); IPFS (4 пина: COMPACT_CONTEXT+nodes.json+старые; координатор 0.15с, skip мёртвых CIDs).
- УТРАЧЕНО (необратимо): 19 старых IPFS-CID (репозиторий пересоздан 2026-07-16); остались в БД как метаданные, помечены SKIP.
- ЗАМЕЧАНИЕ: пароль дашборда в config.yaml — буквальный плейсхолдер __OCTOPUS_DASH_PASS__ (не подставляется; известная дыра — заменить при возможности).

## Хранилище 2026-08-25 — garage/JuiceFS стабилизированы
- Рецепт разблокировки GC garage: `garage repair --yes versions` + `garage repair --yes scrub start` (после массовых удалений).
- JuiceFS TrashDays=0 (корзина отключена — удаления мгновенные).
- Eternal-снапшот: SNAPSHOT_DIR = /var/lib/octopus/snapshots/eternal (прямая ФС; раньше /mnt/swarm → забивал garage).
- Диск 86% (5.2G; ночной бэкап 2.1G уходит в S3 03:00). Garage 2.1G (живые данные), queue 0.
- CI зелёный (tests workflow на prod-main-2026-08-25).
