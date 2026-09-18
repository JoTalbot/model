# Octopus — Parallel All-Vectors Launch Plan
Дата: 2026-07-03
Статус: READY-TO-START, gated execution

## 0. Текущее состояние перед запуском
- SLO: green.
- Disk: 83%, cleanup automation installed.
- RAM: stable, около 2.8/7.6 GiB used.
- Failed systemd units: 0 по последней диагностике.
- Главный ресурсный риск: диск >80%, IPFS repo около 6.8G, /var/lib около 11G.
- Запуск внешних/free-tier ресурсов и разрушительные операции остаются gated.

## 1. Командная модель параллельного развития
Каждый поток работает как bounded wave: backup/read-only audit -> small change -> verify -> report -> next gate.

### Роли
1. Commander / Release Captain
   - держит приоритеты, стоп-флаги, merge/deploy окно;
   - принимает go/no-go после verify каждого batch.
2. SRE / Reliability Lead
   - SLO, restart budget, systemd, Docker/Swarm, disk, rollback.
3. Control Plane Lead
   - DevPanel/Admin UI, control-plane API, safe actions, auth/rate-limit.
4. Memory / CAS Lead
   - CAS, Packstore, IPFS/Garage, durability proofs, live-read verification.
5. RAG / Intelligence Lead
   - GraphRAG, vector search, semantic memory, citations/proofs.
6. Audio / VoxRAG Lead
   - audio ingest, transcription, speaker mapping, CLAP/audio embeddings.
7. Swarm / Autonomy Lead
   - child nodes, orchestration, task reaper, swarm consensus, reputation.
8. Tools / MCP Lead
   - skills MCP, dynamic tools, sandbox/read-only defaults, policy gates.
9. Security / Policy Lead
   - secrets hygiene, command whitelist, audit trail, destructive-op quorum.
10. CI/CD / QA Lead
   - tests, lint, canary deploy, rollback, release notes.

## 2. Глобальные стоп-флаги
Любой поток останавливается и возвращает управление Commander, если:
- SLO != green;
- disk >= 90%;
- failed systemd units > 0 для core-сервисов;
- parent/octopus.service restart без явного deploy окна;
- тесты core падают;
- операция требует удаления Garage/IPFS/CAS данных без live-read + off-host proof;
- внешний ресурс требует оплату, карту или нарушение free-tier limits.

## 3. Векторы и детальные deliverables

### Vector A — Reliability / SLO / Restart Immunity [P0]
Цель: исключить самоповреждения и неконтролируемые рестарты.
Deliverables:
- A1: restart_strategy в registry: none/local_container/ssh_remote/tcp_only.
- A2: restart budget: max 1 restart / 15 min / service, затем quarantine.
- A3: watchdog tests: localhost/tunnel не рестартуют parent.
- A4: health contract: /healthz или явный endpoint mapping.
- A5: dashboard card: restarts, failed units, quarantine.
Verify:
- systemctl --failed = 0;
- octopus test / pytest core pass;
- no parent restart during synthetic child failure.

### Vector B — Storage / Disk / IPFS / Garage [P0]
Цель: удерживать диск <80%, не теряя память.
Deliverables:
- B1: read-only inventory Garage buckets, IPFS repo, containerd, Docker images.
- B2: disk budget policy: alert 80%, freeze noncritical writes 85%, cleanup 90%.
- B3: IPFS GC только при disk >=90% или ручном gate, с pin report.
- B4: heavy ML venv/model relocation plan to worker/off-host.
- B5: daily SRE maintenance/report already installed; добавить weekly storage forecast.
Verify:
- df / <80% target, <85% acceptable;
- no missing CAS/IPFS live-read sample;
- logs/journal/docker logs bounded.

### Vector C — Control Plane / DevPanel / Admin UI [P0/P1]
Цель: единая панель управления без прямого shell для типовых операций.
Deliverables:
- C1: status page: SLO, disk, RAM, load, failed units, service map.
- C2: safe action buttons: report, cleanup proposal, restart canary, rollback.
- C3: action ledger: кто/что/когда/почему/result.
- C4: approval gates for destructive/write actions.
- C5: mobile-friendly command center.
Verify:
- API auth/rate-limit enabled;
- no unauthenticated write actions;
- UI smoke test and API tests pass.

### Vector D — Memory / CAS / Packstore [P1]
Цель: durable memory with proofs.
Deliverables:
- D1: CAS manifest schema: hash, backend, timestamp, source, live-read status.
- D2: packstore read-guard after dedupe/GC.
- D3: memory proof endpoint: item -> hash -> backend -> citation chain.
- D4: backup verify workflow with sample restores.
- D5: memory dashboard: freshness, orphan count, restore drill status.
Verify:
- restore drill pass;
- random sample live-read >= 99%;
- no destructive GC without proof.

### Vector E — GraphRAG / Semantic Intelligence [P1]
Цель: объяснимая память и быстрый поиск решений.
Deliverables:
- E1: graph schema: services, tasks, incidents, decisions, people, artifacts.
- E2: ingestion from reports/logs/experience/docs.
- E3: query modes: fast, deep, incident-review, decision-trace.
- E4: citations to exact files/hashes.
- E5: scheduled GraphRAG maintenance/report.
Verify:
- daily graphrag report exists;
- sample queries return source chains;
- no secrets indexed.

### Vector F — Audio / VoxRAG / Calls [P1]
Цель: production audio memory pipeline.
Deliverables:
- F1: idempotent audio job queue with retries.
- F2: transcript + segments + speaker map in CAS/GraphRAG.
- F3: manual correction UX for speakers/tasks/reminders.
- F4: audio embeddings and cross-modal links.
- F5: privacy gate and retention policy.
Verify:
- new audio upload -> transcript -> memory item -> searchable;
- duplicate upload does not create duplicate memory;
- failed job retries bounded.

### Vector G — Swarm / Task Orchestration / Consensus [P1/P2]
Цель: масштабировать автономность без хаоса.
Deliverables:
- G1: task lifecycle: proposed -> approved -> running -> verified -> archived.
- G2: task reaper policies and dead-letter queue.
- G3: local BFT/Raft pilot for metadata decisions only.
- G4: quorum for destructive swarm actions.
- G5: node reputation as signal, not authority.
Verify:
- synthetic failed task gets reaped;
- no destructive action by single node;
- swarm child failure does not restart parent.

### Vector H — MCP / Dynamic Tools / Skills [P1]
Цель: унифицированный безопасный tool layer.
Deliverables:
- H1: MCP tools: status, report, registry read, logs tail, cleanup proposal.
- H2: write tools require approval token and audit reason.
- H3: command whitelist and denylist.
- H4: tool-call tracing with trace_id.
- H5: skills marketplace/index with tests.
Verify:
- read-only tools work without write permissions;
- write tools blocked without gate;
- all tool calls logged.

### Vector I — Observability / Metrics / Traces [P1]
Цель: причинность, а не только метрики.
Deliverables:
- I1: trace_id in cron/timers/scripts/workflows.
- I2: dashboards: disk forecast, restart budget, workflows, queue lag.
- I3: alert dedupe and known-degraded suppression.
- I4: daily incident digest.
- I5: optional Tempo/Jaeger only after disk <80%.
Verify:
- every report has trace_id;
- alert noise reduced;
- failed workflow visible within 1 reporting cycle.

### Vector J — CI/CD / QA / Release Engineering [P0/P1]
Цель: каждое изменение проверяется до deploy.
Deliverables:
- J1: unit + smoke + systemd lint + stack config validate.
- J2: canary deploy: one child -> parent -> rest.
- J3: rollback script per service group.
- J4: release manifest per wave.
- J5: no direct prod changes without post-change report.
Verify:
- tests pass;
- canary health pass;
- rollback tested on noncritical service.

### Vector K — Security / Policy / Secrets [P0/P1]
Цель: сделать безопасность встроенной в runtime.
Deliverables:
- K1: secret scan excluding intentional secret stores.
- K2: audit log for shell/API actions.
- K3: privilege map for services/users/tokens.
- K4: destructive operations require quorum/gate.
- K5: tunnel exposure inventory.
Verify:
- no secrets in repo/docs/reports;
- public endpoints auth posture known;
- audit record exists for each action.

### Vector L — Product / Business / AutoSklo [P1/P2]
Цель: связать инфраструктуру с продуктовой ценностью.
Deliverables:
- L1: AutoSklo workflows: lead intake, part search, quote, CRM notes.
- L2: human approval for customer-facing messages.
- L3: product dashboard: active leads, tasks, SLA, conversion.
- L4: knowledge base from calls/transcripts/docs.
- L5: weekly business report.
Verify:
- one test lead flows through pipeline;
- no external customer action without human gate;
- measurable lead/task state.

### Vector M — Free-node Expansion / Edge Compute [P2, gated]
Цель: расширять вычисления только бесплатно и безопасно.
Deliverables:
- M1: inventory of existing nodes and free-tier candidates.
- M2: per-provider risk/cost/card requirement matrix.
- M3: bootstrap script for read-only worker node.
- M4: no external creation without explicit gate.
Verify:
- disk <80%;
- P0 stable 24h;
- written approval exists.

## 4. Batch-план запуска

### Batch 0 — Preflight, уже можно выполнить перед стартом
- status green check;
- disk <85% check;
- failed units check;
- recent reports available;
- create launch branch/manifest;
- freeze destructive ops except SRE cleanup.
Exit criteria: launch_board = green.

### Batch 1 — P0 parallel, безопасный старт
Параллельно:
- A: restart_strategy schema + watchdog test plan.
- B: storage read-only inventory + forecast.
- C: control-plane status/action ledger spec.
- J: CI/systemd/docker validation baseline.
- K: public endpoint + secrets exposure inventory.
Exit criteria:
- no service restart except canary;
- reports for A/B/C/J/K exist;
- Commander go/no-go.

### Batch 2 — P1 foundation
Параллельно после Batch 1:
- D: CAS proof endpoint MVP.
- E: GraphRAG schema/index pass.
- H: MCP read-only ops tools.
- I: trace_id propagation in scripts/reports.
Exit criteria:
- all read-only tools verified;
- memory proof sample pass;
- trace visible in report chain.

### Batch 3 — Product and automation expansion
Параллельно после Batch 2:
- F: audio idempotent queue.
- G: task lifecycle/dead-letter queue.
- L: AutoSklo test lead workflow.
Exit criteria:
- no customer-facing automated send without human gate;
- failed jobs bounded;
- product flow demo recorded in report.

### Batch 4 — Scale/edge experiments
Только после 24h green and disk <80%:
- M: free-node proposals;
- G: local consensus pilot;
- optional trace backend if disk allows.
Exit criteria:
- no paid resource;
- no external mutation without approval;
- rollback documented.

## 5. Рабочий ритм
- Wave size: 30–90 минут на поток, bounded.
- Каждый поток пишет report в /root/agents/-Octopus/reports/.
- Каждый поток обновляет experience при новом выводе/инциденте.
- Commander каждые wave-end собирает launch_board.
- Deploy только canary-first.

## 6. Definition of Done для стартовой волны
- Файл launch plan создан.
- Launch board создан.
- Preflight green.
- P0 work packages определены.
- Stop flags известны.
- Нет скрытых destructive actions.
- Следующая команда для старта: START_BATCH_1.
