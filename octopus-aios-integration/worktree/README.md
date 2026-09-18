# Бессмертный Рой (Immortal Swarm) 🐝

Распределённая P2P-сеть автономных ИИ-агентов на Python.

## Быстрый MVP: личные заметки без облака и API-ключей

Gemaxi можно использовать сразу как локальную память: сохранять заметки, смотреть список, искать по тексту и по простому offline-векторному индексу. В этом режиме не нужны OpenRouter, IPFS, Arweave или запущенная P2P-нода.

```bash
# Установка
pip install -r requirements.txt

# Добавить заметку
python node.py note add Клиент Иван заказал лобовое стекло на Lada Granta --tag clients --tag orders --title "Заказ Иван"

# Посмотреть заметки
python node.py note list

# Найти заметки
python node.py note search "стекло granta"

# Собрать RAG-промпт по заметкам без вызова внешней LLM
python node.py note ask "Что заказал Иван?"
```

Данные по умолчанию сохраняются локально в `.swarm_scratch/`.

## Архитектура

```
┌────────────────────────────────────────┐
│  CLI (node.py)                         │
├────────────────────────────────────────┤
│  Agent Layer                           │
│  ├── SwarmAgent (core.py)              │
│  ├── TaskManager (task_manager.py)     │
│  └── Skills (skills.py)               │
├────────────────────────────────────────┤
│  Memory Layer                          │
│  ├── DistributedMemory (store.py)      │
│  └── ErasureCoder (erasure.py)         │
├────────────────────────────────────────┤
│  Network Layer                         │
│  ├── Kademlia DHT (kademlia.py)        │
│  ├── Gossip Protocol (gossip.py)       │
│  └── RPC Server/Client (rpc.py)        │
├────────────────────────────────────────┤
│  LLM Layer                             │
│  ├── LLMRouter (router.py)             │
│  └── KeyPool (key_pool.py)             │
└────────────────────────────────────────┘
```

## Быстрый старт

```bash
pip install -r requirements.txt
python node.py start --port 8000
```

Второй узел (с бутстрапом):

```bash
python node.py start --port 8001 --bootstrap 127.0.0.1:8000
```

## Ключевые технологии

- **Kademlia DHT** — peer discovery и distributed key-value storage
- **Gossip Protocol** — push-based UDP broadcasts (задачи, события)
- **Reed-Solomon Erasure Coding** — stripe-based шардирование памяти
- **OpenRouter LLMs** — мультимодельный failover с пулом ключей
- **RPC (msgpack + TCP)** — прямое взаимодействие между нодами

## Тесты

```bash
python -m pytest -v
```

Unit и integration тесты (`pytest`).

## Конфигурация

Редактируй `config.yaml`:

```yaml
llm:
  keys: ["sk-your-key-1", "sk-your-key-2"]
  models: ["anthropic/claude-sonnet-4-20250514", "x-ai/grok-3-mini-beta"]
```

## Структура проекта

```
swarm/
├── agent/       # Ядро агента, декомпозиция задач, скиллы
├── memory/      # Erasure coding + distributed store
├── network/     # Kademlia, Gossip, RPC
└── llm/         # Router с failover, пул ключей
tests/           # pytest
node.py          # CLI entry point
config.yaml      # Настройки по умолчанию
```

Спек → план → задачи (без Notion): [`docs/spec-to-implementation.md`](docs/spec-to-implementation.md), черновики планов — [`docs/plans/`](docs/plans/).



## Local LLM (offline mode)

Gemaxi can run **completely offline** using a local LLM server instead of (or alongside) OpenRouter. Any server that exposes an **OpenAI-compatible** `POST /v1/chat/completions` endpoint will work.

### Supported servers

| Server | Install | Default endpoint |
|--------|---------|-----------------|
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | `brew install llama.cpp` / build from source | `http://127.0.0.1:8080/v1` |
| [Ollama](https://ollama.com) | `curl -fsSL https://ollama.com/install.sh \| sh` | `http://127.0.0.1:11434/v1` |
| [vLLM](https://docs.vllm.ai) | `pip install vllm` | `http://127.0.0.1:8000/v1` |
| [LM Studio](https://lmstudio.ai) | Desktop app | `http://127.0.0.1:1234/v1` |

### Quick start with llama.cpp

```bash
# 1. Download a GGUF model (example: Llama 3.3 70B Q4)
wget https://huggingface.co/bartowski/Llama-3.3-70B-Instruct-GGUF/resolve/main/Llama-3.3-70B-Instruct-Q4_K_M.gguf

# 2. Start llama-server
llama-server -m Llama-3.3-70B-Instruct-Q4_K_M.gguf \
    --host 127.0.0.1 --port 8080 \
    -c 8192 -ngl 99

# 3. Verify it works
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama-3.3-70b","messages":[{"role":"user","content":"Hello"}]}'
```

### Quick start with Ollama

```bash
# 1. Pull a model
ollama pull llama3.3:70b

# 2. Ollama auto-starts; verify
curl http://127.0.0.1:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.3:70b","messages":[{"role":"user","content":"Hello"}]}'
```

### Configuration

#### Local-only (no cloud keys)

```yaml
llm:
  keys: []        # no OpenRouter keys needed
  models: []      # empty — all inference is local
  local:
    enabled: true
    base_url: "http://127.0.0.1:8080/v1"
    models: ["llama-3.3-70b"]
    prefer_local: true
```

#### Hybrid (cloud primary, local fallback)

```yaml
llm:
  keys: ["sk-or-v1-YOUR-KEY"]
  models: ["anthropic/claude-sonnet-4-20250514", "meta-llama/llama-3.3-70b-instruct"]
  local:
    enabled: true
    base_url: "http://127.0.0.1:8080/v1"
    models: ["llama-3.3-70b"]
    prefer_local: false   # try cloud first; local when cloud fails
```

#### Hybrid (local primary, cloud fallback)

```yaml
llm:
  keys: ["sk-or-v1-YOUR-KEY"]
  models: ["anthropic/claude-sonnet-4-20250514"]
  local:
    enabled: true
    base_url: "http://127.0.0.1:8080/v1"
    models: ["llama-3.3-70b"]
    prefer_local: true    # try local first; cloud as safety net
```

### Model aliases

Agent configs reference cloud model names like `meta-llama/llama-3.3-70b-instruct`. When running locally, these names don't match the model name your local server uses (e.g. `llama-3.3-70b`). **Model aliases** solve this:

```yaml
llm:
  local:
    enabled: true
    base_url: "http://127.0.0.1:8080/v1"
    models: ["llama-3.3-70b"]
    prefer_local: true
    model_aliases:
      "meta-llama/llama-3.3-70b-instruct": "llama-3.3-70b"
      "anthropic/claude-sonnet-4-20250514": "llama-3.3-70b"
      "x-ai/grok-3": "llama-3.3-70b"
```

Now the same agent configs work both online and offline — the router transparently maps cloud names to local names.

### How the fallback chain works

```
Request: complete(messages, model="meta-llama/llama-3.3-70b-instruct")

prefer_local=false (default):
  1. Cloud: openrouter.ai → meta-llama/llama-3.3-70b-instruct
  2. Local: 127.0.0.1:8080 → llama-3.3-70b (via alias)

prefer_local=true:
  1. Local: 127.0.0.1:8080 → llama-3.3-70b (via alias)
  2. Cloud: openrouter.ai → meta-llama/llama-3.3-70b-instruct
```

Each target is retried `max_retries` times before moving to the next.

### Optional: authentication

If your local server requires a Bearer token:

```yaml
llm:
  local:
    api_key: "your-local-token"
```

## Web Parser Pipeline

The parser pipeline extracts structured product/offer data from web pages. It resolves URLs (direct or via search), fetches HTML, extracts text with `selectolax`, and structures offers via LLM into JSON.

### CLI

```bash
# Parse a single URL
python node.py parse https://shop.example.com/catalog

# Search and parse (Yandex → DuckDuckGo fallback)
python node.py parse "autoglass lada granta price" --search --limit 5

# JSON output
python node.py parse https://example.com --json

# Persist results to local memory
python node.py parse https://example.com --save
```

### Pipeline Architecture

```
Input (URL | query)
    → Resolver (Yandex → DuckDuckGo HTML fallback)
    → list[url]
    → Fetcher (httpx, UA rotation, 512KB cap, polite delay)
    → Extractor (selectolax text → LLM → JSON)
    → ParseResult (per URL) + merged CLI view
```

### Configuration

Optional section in `config.yaml`:

```yaml
parser:
  fetch_timeout_seconds: 15
  max_response_bytes: 524288
  max_urls_per_query: 10
  llm_text_max_chars: 4000
  polite_delay_seconds: 1
```

## Optional: memory facade

The **MemoryPort** facade under `swarm/memory` exposes a small async API over `ref:<scheme>:<opaque>` and composes a local scratch store with the erasure-coded swarm store.

- Set `memory_facade.enabled: true` in `config.yaml` to build the facade on a **running node** (default `false` keeps behavior unchanged).
- Anonymous **cloud paste** backends are also wired for **offline CLI** whenever their flags are `true` under `memory_facade.cloud_paste` — no need to start the node. For **no API key**, use **`pasters`** (paste.rs) or **`catbox`**. **paste.ee** needs a free Application key (`pasteee_api_key` or `PASTE_EE_API_KEY`). **`nullpointer`** / **`dpaste`** are often policy-disabled.
- `scratch_root` controls where the `file` adapter persists blobs; paths support `~` expansion.
- With `enabled: true`, the node must pass a live `DistributedMemory` into `build_memory_port`; otherwise the factory raises `MemoryAdapterError` because the `swarm` adapter has no backend.
- `default_put_route` (`file` or `swarm`) records the preferred default for `put` in configuration (see plan/spec for how routing maps to artifacts).
- **WORM on scratch:** route `dur:worm` with `worm_base_ref` pointing at an existing `ref:file:…` rejects a second `put` with different bytes (`WormConflictError`); identical bytes are idempotent.
- **Shard repair:** `memory.repair_interval_seconds` (default `0`) starts a background loop in `SwarmAgent` that calls `DistributedMemory.scan_and_repair_round`. Missing shards can be pulled from peers via RPC `memory_shard_get` (see `docs/superpowers/specs/2026-05-14-shard-repair-rpc-design.md`).
- **HTTP(S) refs:** `memory_facade.http_links.enabled: true` with a non-empty `http_links.allowlist` registers read-only `ref:https:…` / `ref:http:…` (`LinkAdapter`) using the same host/IP guard as paste fetches.
- **Outbound proxy:** `network.outbound_proxy` (optional) applies to paste/link `httpx` clients and to `LLMRouter` (OpenRouter etc.); use e.g. `socks5://127.0.0.1:9050` with Tor. P2P sockets are not tunneled.

### Immortal memory layers

The facade composes **22+ schemes** (cloud flags + optional `http`/`https`) so the swarm survives almost any failure mode:

| Layer | Schemes |
| --- | --- |
| Local | `file` (LocalScratch, WORM-capable) |
| Distributed | `swarm` (Kademlia + Reed-Solomon shards) |
| Wiki | `obsidian` (Markdown vault, Karpov-style `[[wiki-links]]`) |
| Optional URL fetch | `https`, `http` (allowlist-driven; off by default) |
| Free anonymous (no auth; **paste.ee needs app key**) | `nullpointer`, `catbox`, `fileio`, `dpaste`, `ixio`, `telegraph`, `rentry`, `pasteee`, `termbin`, `tmpfiles`, `transfersh`, `sprunge`, `pasters`, `hastebin`, `pixeldrain`, `filebin`, `litterbox`, `bashupload`, `clbin` |

Enable cloud adapters in `config.yaml`:

```yaml
memory_facade:
  enabled: true
  obsidian: { enabled: true, vault_root: ".swarm_scratch/wiki" }
  cloud_paste:
    pasters: true
    pasteee: true
    pasteee_api_key: "your-paste-ee-application-key"
    catbox: true
    telegraph: true
    rentry: true
    # … turn on any subset
```

Use `artifact.attrs["store"] = "<scheme>"` to route an individual put, or hand the artifact to `Replicator.replicate(...)` to fan it across many backends in parallel.

### Memory as a DB

`MemoryRepository` turns the facade into a JSON-document store with `save / query / count / distinct / latest / delete` and a small `WHERE`-like filter (`data.<key> == "x" and attrs.price >= 100`).

CLI:

```bash
python node.py memory insert --table parts --data '{"v":1}'
python node.py memory insert --table parts --data '{"v":1}' --store pasters
python node.py memory query  --table parts --order-by attrs._ts:desc --limit 10
python node.py memory metrics                                  # per-scheme metrics table
python node.py memory metrics --json                           # /metrics-style snapshot
```

### Vector memory (TF-IDF / hashing, no numpy)

`swarm.memory.vector_store` provides `HashingEmbedder`, `TfIdfEmbedder`, `VectorStore` and `PersistentVectorIndex`, which serialises every record into the `vector_index` table of the repository — so vectors inherit every redundancy layer above for free.

```bash
python node.py memory vector-add --id p1 --text "автостекло lada granta"
python node.py memory vector-search "автостекло" --top 5
```

### Knowledge graph & visualisation

`swarm.memory.graph` builds three graph flavours (wiki / metrics / repository) and renders them as DOT, Mermaid, JSON or plain ASCII.

```bash
python node.py memory wiki  --title "Index" --body "see [[Other]]" --tag kb
python node.py memory graph --kind wiki     --format mermaid
python node.py memory graph --kind metrics  --format dot      | dot -Tsvg -o metrics.svg
python node.py memory graph --kind repository --format ascii
```

### Universal file dropper (FileDropbox)

`swarm.memory.dropbox.FileDropbox` turns the memory facade into a public file-sharing service.  Drop in any file (any size, binary or text), get back one short ref; hand the ref to anyone and they can reassemble the file as long as the swarm + at least one cloud per chunk is alive.

How it works:

- The file is split into fixed-size chunks (default 256 KB so each chunk fits typical anonymous paste limits; pick `--chunk-size` to match backends you enable, e.g. larger slices for high-limit hosts).
- Every chunk is uploaded to `replication` independent backends in parallel via the existing `Replicator`.
- A JSON manifest (name, mime, size, sha256, per-chunk locators) is itself replicated to several backends and the manifest's ref is what the caller shares.
- `download(ref)` walks each chunk's replicas in order, verifies sha256, and assembles the file; if one cloud dies the next replica is tried automatically.
- `health(ref)` pings every replica without downloading the body — handy for monitoring.

CLI:

```bash
python node.py memory dropbox-upload  path/to/big.zip --replication 3 --chunk-size 262144
# -> dropbox:ref:catbox:https://files.catbox.moe/xyz.json
python node.py memory dropbox-info     dropbox:ref:catbox:... --json
python node.py memory dropbox-health   dropbox:ref:catbox:...
python node.py memory dropbox-download dropbox:ref:catbox:... --out restored.zip \
       --mirror dropbox:ref:nullpointer:https://0x0.st/Ab
```

The `--mirror` flag lets the caller pass extra manifest mirrors so the
download survives the loss of any single anonymous storage that held a
manifest copy.

### Disaster recovery

`swarm.memory.recovery` gives the swarm three independent failsafes:

- `Replicator.replicate(artifact, schemes=...)` — fan a single artifact into many backends concurrently; returns per-scheme outcomes.
- `SwarmSnapshot.dump() / restore()` — JSONL bundle of every reachable record; `target_scheme` lets you rehydrate a fresh node from a single Telegraph URL.
- `BootstrapManifest` — self-describing JSON listing seed peers and important refs; `publish` sprays the manifest itself across N anonymous storages, `fetch` pulls it back from any reachable adapter.

CLI helpers:

```bash
python node.py memory snapshot --out snap.jsonl --kind repository
python node.py memory restore  snap.jsonl --kind repository --target-scheme obsidian
python node.py memory bootstrap-manifest \
    --out manifest.json \
    --seed 10.0.0.1:8000 --seed node.example:9000:kademlia \
    --entry ref:nullpointer:https://0x0.st/Ab:purpose=manifest_mirror \
    --notes "phone-only seed"
```

The combined effect: a single bootstrap-manifest URL on any one of the 19 anonymous storages is enough to rejoin the swarm from a fresh device with no saved credentials.

### Phase 3: production-grade memory toolkit

Everything above is still in play; this section catalogs the modules added in the **immortal-memory-phase-3** stack on top of the original 14-adapter facade.

#### 🔒 Security & privacy

- **E2E encryption** (`swarm.memory.crypto`) — `EncryptedMemoryPort` middleware transparently AES-256-GCM-seals every artifact before it touches an adapter. Key derivation via Scrypt (PBKDF2-HMAC-SHA256 fallback).
- **Ed25519 signatures** (`swarm.memory.signing`) — `SignedMemoryPort` middleware signs every put and verifies every get. Detects content / attrs / tags / mime tamper; supports `require_known_signer=True` for strict allowlists.
- **Audit log** (`swarm.memory.audit`) — `AuditedMemoryPort` writes one JSONL line per memory op (ts/op/ref/scheme/ok/bytes/latency/agent/error), with daily rotation and a `stats()` aggregator. Audit-log failures never break the underlying op.
- **Zero-knowledge dropbox** (`swarm.memory.zk_dropbox`) — `ZkDropbox` encrypts the entire file client-side and embeds the AES key in the URL fragment (`zk:...#key=...`). The swarm holds only ciphertext; the key never crosses the wire.

#### 🌐 Resilience & sneakernet recovery

- **Smart routing** (`swarm.memory.routing`) — `SmartReplicator` ranks schemes by `availability * exp(-p95 / HALFLIFE)` and picks the top-k for each put, with automatic fallback when the first wave underdelivers.
- **QR bootstrap** (`swarm.memory.qr`) — `qr_terminal(data)` renders any short ref / share link as a phone-scannable terminal QR. Pair with `zk-upload` for a single-photograph file handoff.
- **memory doctor** — bulk `port.exists()` probe over a list of refs with per-scheme summary, latency stats, JSON or text output. Exit 1 if any ref is broken (CI-friendly).
- **consolidate** — TTL-based GC + exact-duplicate detection (blake2b of canonical payload, ignoring `_ts`) + near-duplicate Jaccard pruning. Plan-then-apply with `keep_newest` semantics.

#### 📊 Observability & ops

- **Prometheus exporter** (`swarm.memory.prom`) — `render_metrics(metrics, audit_stats)` emits standard exposition format: `swarm_memory_puts_total{scheme}`, `swarm_memory_gets_total{scheme,status}`, `swarm_memory_availability`, `swarm_memory_latency_ms{quantile}`, `swarm_memory_audit_total{scheme,ok}`, …
- **Web dashboard** (`swarm.memory.dashboard`) — stdlib-only `http.server` exposing `/` (HTML), `/metrics` (Prometheus), `/api/metrics` (JSON), `/api/audit` (JSON), `/healthz`. No aiohttp / Flask — drops onto any cheap VPS / Termux / RasPi.
- **SQL gateway** (`swarm.memory.sql_gateway`) — `SqlMirror` rebuilds a SQLite read-side projection of `MemoryRepository` (tables `records` + `record_tags`) so operators can run arbitrary `JOIN` / `GROUP BY` / window-function queries via the standard `sqlite3` CLI.

#### 🧠 Retrieval & ML

- **RAG** (`swarm.memory.rag`) — `Retriever` for top-K cosine + `HybridRetriever` for vector∪tag union; `build_prompt(query, docs)` renders a deterministic, citation-friendly prompt that any LLM backend can consume. LLM-agnostic by design.

#### 📱 Phone-side control

- **Telegram bot** (`swarm.memory.telegram`) — long-polling bot using only `httpx` (already a dep). Replies only to chats passed as `--allow` (secure default); `--open-access` exists for disposable tokens/tests only. Exposes `/status` (Prometheus-style snapshot), `/list TABLE`, `/insert TABLE key=value`, `/rag QUERY`, `/qr DATA`.

#### New CLI commands

```bash
# Observability
python node.py memory doctor --ref ref:catbox:... --ref ref:nullpointer:... --json
python node.py memory dashboard --demo --port 9100

# SQL mirror
python node.py memory sql-sync  --out mirror.db
python node.py memory sql-query "SELECT table_name, COUNT(*) FROM records GROUP BY table_name" --db mirror.db

# Sneakernet recovery
python node.py memory bootstrap-qr --data "zk:dropbox:ref:catbox:...#key=..."

# Zero-knowledge file sharing
python node.py memory zk-upload  /path/big.zip --replication 3
python node.py memory zk-download "zk:dropbox:ref:catbox:...#key=..." --out restored.zip

# Retrieval-augmented generation
python node.py memory rag "Какое стекло у BMW X5?" --top 5

# Cleanup
python node.py memory consolidate --ttl 86400 --apply

# Phone-side control
TELEGRAM_BOT_TOKEN=... python node.py memory tg-bot --allow 1234567
# Insecure (every chat): add --open-access — never on a real token
```

## Optional: LAN discovery (mDNS)

Опционально: установите зависимости для обнаружения пиров в локальной сети (LAN peer discovery). Тот же код на Windows и Linux.

Optional install for LAN peer discovery; same codebase on Windows and Linux.

```bash
pip install -r requirements-mdns.txt
```

Включите `mdns.enabled: true` в `config.yaml`, откройте файрвол для UDP 5353 (mDNS) и портов узла (Kademlia, gossip, RPC) — enable `mdns.enabled: true` in `config.yaml`, open firewall for UDP 5353 (mDNS) and node ports (Kademlia, gossip, RPC).

## Personal Memory OS (Gemaxi Upgrade 2026) 🧠

The 2026 upgrade transforms Gemaxi into a **Personal Memory Operating System**. Information is no longer just "files in folders" but a **living semantic graph** that is immortal, distributed, and self-organizing.

### Key Upgrade Features

- **Semantic VFS**: A Virtual File System where every file is a node in your knowledge graph.
- **Hierarchical Memory**:
    - **Hot Layer**: Vector Store for instant AI recall.
    - **Warm Layer**: Structured metadata and relational links in a Repository.
    - **Cold Layer**: Immutable, encrypted storage on **IPFS** and **Arweave** (200+ years survival).
- **P2P State Sync**: CRDT-based synchronization between all your devices (PC, Phone, Server) via Gossip protocol.
- **Autonomous Agents**:
    - **Linker Agent**: Automatically discovers semantic connections between your memories.
    - **Archivist Agent**: Identifies high-value information and ensures its permanent preservation.
- **Time Machine**: Query your entire digital life at any point in history.

### Memory OS CLI

```bash
# Import a file into your semantic OS
python node.py vfs import my_notes.txt --dest /projects/ai --tags "notes,swarm"

# List virtual directories
python node.py vfs ls /projects/ai

# Semantic search across all your files and chats
python node.py vfs search "what did I think about decentralized AI?"

# Travel back in time
python node.py timemachine --at 1715690000

# Archive important ref to cold storage manually
python node.py immortal archive ref:file:xyz --importance 0.9
```

### Architecture: The Memory OS Stack

| Layer | Component | Tech Stack |
| --- | --- | --- |
| **Interface** | CLI / VFS / Dash | Click, Svelte (Plan) |
| **Agents** | Linker, Archivist | Gemini / Claude / Llama |
| **Sync** | SyncEngine | CRDT + Gossip |
| **Memory** | Hot/Warm/Cold | VectorDB / SQLite / Arweave |
| **Transport**| P2P / RPC | Libp2p / Kademlia |
