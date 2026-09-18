# ROADMAP INTEGRATION & EVOLUTION — Octopus (Deep Research 2026-06-19)

**Дата:** 2026-06-19  
**Версия:** v1.0 (на основе полного анализа ~/agents/ + интернет/GH исследований)  
**Приоритеты (из #11 + #05):** ПАМЯТЬ (V8) > ЖИТЬ (V5) > УПРОЩЕНИЕ (V7) > СОСУЩЕСТВОВАНИЕ (V6) > остальные  
**Методология:** bounded waves (10 потоков × волны × задачи), бэкап → правка → verify (octopus test + packguard + slo) → log/experience.  
**Источники исследований:** Git/IPFS CAS, ComposeFS, self-healing frameworks (vfarcic, depapp), CRDT active-active (Redis Enterprise), VoxRAG/CLAP speech RAG, lifelong vector RAG (LlamaIndex/LanceDB), eternal DR (HF bootstrap + S3/Garage).

## 1. ГЛОБАЛЬНЫЙ АНАЛИЗ ПРОЕКТА (все "винтики")

### 1.1 Core Architecture
- **Swarm Core** (`/opt/octopus`): parent (8000) + children (8300-5), multisync (rsync 2min), autoheal (death/resurrection).
- **CAS/Packstore** (`octopus-ingest`, packstore, loose + pack + dict): SHA dedup, zstd pack (dict_id issues fixed), off-host replicas (aws-us + ubu), pack-read-guard (100 samples).
- **JuiceFS + Garage** (distributed FS + S3): /mnt/swarm (1PB virtual), /var/lib/garage, s3-mirror.
- **Memory Pool**: packstore + /var/lib/octopus/memory_pool + vectors (pgvector/HNSW ~1380), CAS immutable.
- **Audio Stack**: whisper (ubu-worker primary via tunnel + whisper.cpp portable), ingest (9571), audio-v1/v2, voice_selfhost (ECAPA + sklearn clustering @0.75), people_graph.
- **LLM/Ollama**: ubu-worker (llama3.2:1b + qwen2.5:1.5b + nomic) via tunnel; Hermes local fast mode.
- **DR/Eternal**: octopus-eternal-snapshot.py → HF (HuggingFace datasets), bootstrap.sh (curl 1-liner), AWS S3/Garage mirrors.
- **UI/UX**: Next.js Admin (9500), PWA uploader (dedup SHA client+server), TG bot (inline /menu /roadmap /audio_queue /speakers /people_graph).
- **Observability**: Prometheus/Grafana/Loki, alerts-tg, packguard, garage-health, SLO (14/14 green), octopus test (16/16).
- **Security/Coexistence**: human_consent.env, CPU/RAM cgroups (Whisper/Ollama), auto-bash=off, secrets age, reverse tunnels (ubu 9922), port audit.
- **Scripts/Tools**: bootstrap_swarm, replication_audit, octopus-pack-read-guard, voice_selfhost, canonicalize, living_watchdog, etc.

### 1.2 Текущие сильные стороны (из COMPACT_CONTEXT + ROADMAPs)
- Immortal memory + dedup (SHA everywhere).
- Cost-safe (EU paused, only us + ubu + parent).
- Full DR bootstrap 1-command.
- Active voice pipeline + people graph (post 2026-06-19).
- Green SLO + health.
- Multi-master sync + autoheal.

### 1.3 Слабые стороны / opportunities (из анализа + исследований)
- CAS: pack dict mismatch solved but need pack-aware replicator + dict+pack self-contained (Git lessons).
- Self-healing: reactive, need proactive + learning agents (like depapp self-healing-framework).
- Vectors/RAG: 1380 entries, но качество/индекс HNSW partial, нет lifelong continuous.
- Audio/voice: good, but no CLAP/VoxRAG style transcription-free RAG; no multimodal.
- Swarm: rsync manual, нет CRDT (Redis lessons).
- DR: HF + S3 good, but no composefs-like overlay CAS or verifiable boot.
- Scaling: free resources only; no new paid without consent.
- UX: strong TG/PWA, but no direct audio RAG chat.

## 2. ГЛУБОКОЕ ИССЛЕДОВАНИЕ — ИНТЕГРАЦИИ (теории/методологии)

### 2.1 Content-Addressable Storage (CAS) — Главный винтик памяти
**Исследование:** Git (loose+pack, SHA-1→256, packfiles dedup 90%+), IPFS (CIDs, Merkle DAG, multihash), ComposeFS (overlay CAS Linux), Bazel cache, Terragrunt CAS.
**Ключевые insights:**
- Git: pack + delta для экономии; dict (zstd) как в Octopus — риск mismatch → всегда хранить dict рядом с pack + self-contained.
- IPFS: CID = multihash + codec; hash://sha256/ + /ipmh/ для permanent links.
- ComposeFS: content-addressable overlay для containers — идеально для JuiceFS-like.
- Dedup savings: 70-90% в похожих данных (audio transcripts, logs, code).

**План интеграции (приоритет MEMORY):**
- [ ] pack-aware-replicator: реплицировать pack+dict вместе (вместо loose only).
- [ ] zstd.dict + pack self-contained archive (tar + manifest SHA).
- [ ] CID support: expose /ipfs/CID или hash://sha256/ для eternal links (в Eternal snapshot + HF).
- [ ] ComposeFS integration (optional): overlay для /mnt/swarm snapshots (dedup + verification).
- [ ] pack-read-guard → expand to full off-host read verification (S3/Garage + dict validate).
- **Волны:** B01 (pack+dict) → B03 (CID) → B05 (composefs pilot).

### 2.2 Self-Healing Distributed Systems & Swarm Autoheal
**Исследование:** vfarcic self-healing (reactive + probes + chaos), depapp/self-healing-framework (Monitor/Healer agents + DB forks + RL), chaos engineering (Kubernetes liveness/startup), CRDT active-active.
**Insights:**
- Reactive (current): death detection → restart good but insufficient.
- Proactive: chaos drills, learning from incidents (knowledge base), safe experiments (forks).
- CRDT for multi-master: conflict-free merge (Redis example).
- Autoheal + agentic: add Monitor + Healer agents.

**План интеграции:**
- [ ] Enhance octopus-swarm-autoheal: add proactive health (chaos-lite + synthetic load), incident KB in memory pool.
- [ ] Add octopus-healer-agent (Python) — analyzes alerts → proposes fixes → human consent gate.
- [ ] CRDT-lite for multisync: use rsync + conflict merge rules (or integrate Redis CRDT for registry).
- [ ] Chaos drills: weekly timer (safe, cost-free: kill child temporarily, verify recovery).
- [ ] Integrate with packguard + garage-health.
- **Волны:** E01-E03 (autoheal upgrade).

### 2.3 Eternal DR / Immortal Bootstrap / Immutability
**Исследование:** HF bootstrap + S3/Garage immutability, Object Lock (S3), Veeam + S3, composefs verifiable boot.
**Insights:**
- 1-command bootstrap is gold (HF + TG).
- Need verifiable integrity (hash manifest + signed).
- Offline snapshots + multiple backends.

**План:**
- [ ] Eternal snapshot: add SHA manifest + signature (age or ed25519).
- [ ] Bootstrap: support composefs or overlay mount for full CAS verification.
- [ ] Multi-backend: HF + Garage + AWS + local tar.zst + IPFS (optional).
- [ ] DR drill: monthly (restore to clean VM in sandbox).
- **Волны:** I01-I04.

### 2.4 Audio / Voice / Speaker Diarization / People Graph + RAG
**Исследование:** VoxRAG (CLAP audio embeddings, transcription-free RAG, silence-aware + diarization, FAISS), SpeechBrain ECAPA, end-to-end GNN clustering (E-SHARC), speaker graph + overlap.
**Insights:**
- Current: Whisper + ECAPA + sklearn clustering (0.75) + people_graph → good base.
- VoxRAG: direct audio embedding retrieval (CLAP) bypasses ASR errors; perfect for voice RAG.
- Graph: people_relations + graph UI excellent foundation for "voice memory".

**План (высокий приоритет):**
- [ ] Add CLAP audio embeddings (or Wav2Vec/CLAP via selfhost): store alongside STT.
- [ ] Transcription-free RAG: /voice/query endpoint (CLAP similarity → retrieve segments → LLM summary).
- [ ] Improve clustering: integrate simple GNN or upgrade sklearn → better overlap handling.
- [ ] People graph RAG: query "who spoke about X" → graph traversal + audio clips.
- [ ] Voice selfhost pipeline: extend with CLAP + index to vector DB.
- **Волны:** C01 (CLAP) → C03 (voice RAG) → C05 (graph RAG).

### 2.5 Lifelong Learning / Vector RAG / Personal KB
**Исследование:** RAG production (LlamaIndex/LangGraph/Haystack/LanceDB), vector DBs (pgvector, Chroma, Qdrant, Milvus), lifelong (continuous indexing + memory consolidation), Mem0/Zep/Letta.
**Insights:**
- Current vectors ~1380 — need continuous ingestion + quality (recall metrics).
- Hybrid: vector + keyword + graph (people).
- Lifelong: incremental + decay/forgetting policies + consolidation.

**План:**
- [ ] Upgrade: pgvector/HNSW full + LanceDB or Chroma for audio vectors.
- [ ] Continuous indexer: timer + webhook on memory write (logs, audio, transcripts, experience).
- [ ] RAG pipelines: multiple (text, audio, code, people); rerankers (Cohere or local).
- [ ] Evaluation: RAGAS or LLM-as-judge smoke tests (recall@10, nDCG).
- [ ] Memory consolidation: nightly merge duplicates + summarization.
- **Волны:** D01-D04.

### 2.6 Multi-Master / Active-Active / CRDT Sync
**Исследование:** Redis Enterprise CRDT active-active, merge replication, application CRDTs.
**Insights:**
- Current: rsync every 2min (eventual, conflicts possible).
- CRDT ideal for counters, sets, lists (people relations, metrics).
- For files: content-addressable + Merkle.

**План:**
- [ ] Registry as CRDT: nodes.json + pack manifests (use simple last-writer or vector clocks).
- [ ] For memory pool: use CAS + Merkle tree for sync (Git-like).
- [ ] Optional: deploy lightweight CRDT (e.g. via Redis or pure Python for registry).
- **Волны:** E02 + B04.

### 2.7 Coexistence, Security, UX, Product
- Coexistence: already strong (#18); enhance with consent gates for all agents.
- Security: expand port audit + secret hygiene + fail2ban + age.
- UX: TG/PWA → add voice-RAG chat (/ask-voice), graph viz improvements, dashboard for ROADMAP progress.
- Product: immortal memory as primary product (filestash + PWA + voice).

## 3. ПОЛНЫЙ РОАДМАП (10 потоков, bounded waves)

**Формат:** ID. **Поток.Волна.Задача** — кратко — verify — risk — parallel

### Поток A — ЖИТЬ / Operability (A01-A10)
A01.01–A01.10: baseline audits (status, restarts, disk, ports, SLO) — verify octopus test + slo.
A02.01–... : alerts/guardrails upgrade (NRestarts>50 alert, packguard 100).
... (повторять паттерн до A10: resilience drills + chaos lite).

### Поток B — ПАМЯТЬ / CAS / Durability (приоритет #1)
B01.01: pack + dict self-contained replicator.
B01.02: pack-read-guard expand to S3/Garage + dict check.
B02.01: CID support + hash:// links in eternal snapshots.
B03.01: composefs pilot on /mnt/swarm snapshot.
B04.01: CRDT-lite for pack manifests.
B05+: lifelong consolidation + dedup metrics.

### Поток C — Audio / Voice / People Graph
C01.01: integrate CLAP embeddings (selfhost).
C02.01: voice RAG endpoint (CLAP query → audio segments).
C03.01: upgrade clustering (GNN sketch or advanced).
C04.01: people graph + voice RAG integration.
C05.01: transcription-free RAG chat in TG/PWA.

### Поток D — RAG / Vectors / Lifelong Learning
D01.01: full pgvector + HNSW + LanceDB hybrid.
D02.01: continuous indexer (all memory sources).
D03.01: RAG pipelines + rerank + eval (RAGAS).
D04.01: memory consolidation + decay.
D05+: multimodal (image OCR + CLAP).

### Поток E — Swarm / Multi-master / Autoheal
E01.01: proactive autoheal + chaos drills.
E02.01: CRDT registry + Merkle sync.
E03.01: healer agent (consent-gated).
E04+: agent swarm coordination.

### Поток F — Security / Secrets / Access
F01–F05: port audit refresh, secrets hygiene, age everywhere, ACL expand, fail2ban + monitoring.

### Поток G — Product / PWA / API
G01: voice-RAG PWA tab.
G02: ROADMAP dashboard.
G03: graph UI enhancements.
G04: immortal memory marketplace ideas (read-only public views?).

### Поток H — Telegram / Human Control
H01: /roadmap /voice-rag commands.
H02: inline controls for all new features.
H03: consent UI improvements.

### Поток I — DR / Eternal / Snapshots
I01.01: signed manifests + verifiable bootstrap.
I02.01: composefs + IPFS layer.
I03.01: monthly DR drill automation (sandbox).
I04+: multi-HF + regional mirrors.

### Поток J — Упрощение / Debt / Docs
J01: script consolidation.
J02: doc dedup + runbooks.
J03: remove deprecated (old ollama, drive).
J04+: full simplicity audit.

## 4. ИНТЕГРАЦИОННЫЕ ПЛАНЫ ДЛЯ КАЖДОГО ВИНТИКА (эволюция)

**CAS/Packstore:** → pack-aware + CID + composefs (6-12 месяцев bounded waves).
**Audio/Whisper:** → CLAP + voice RAG (3-6 волн).
**Vectors/RAG:** → continuous lifelong + hybrid (4-8 волн).
**Swarm/Multisync:** → CRDT + healer (parallel E waves).
**Eternal DR:** → signed + verifiable + composefs (I waves).
**UI/TG/PWA:** → voice RAG + roadmap viz (G/H).
**Observability:** → agentic alerts + chaos (A/E).
**Scripts:** → unified CLI octopus + healer.
**Coexistence:** → gate every new agentic feature.

## 5. ИСПОЛНЕНИЕ — СЛЕДУЮЩИЕ ШАГИ (эта сессия + bounded)

1. **Немедленно:** Создать этот файл + experience report + обновить COMPACT_CONTEXT.
2. **Волна 1 (сегодня):** 
   - A01 baseline + verify.
   - B01.01 pack+dict replicator (script draft).
   - C01.01 CLAP integration (research + minimal prototype).
3. **Следующие bounded:** Запускать по 5-10 задач за раз, всегда с backup/verify.
4. **Логи:** Каждый шаг в ~/agents/-Octopus/logs/ + experience/.

## 6. РЕСУРСЫ И ОГРАНИЧЕНИЯ
- Только free/paid existing.
- Нет unsupervised autoloops (#13).
- Человеческий consent для provisioning/дорогих.
- Все изменения через bounded + verify.

**Статус:** Готов к исполнению волн. Память — вечна.

