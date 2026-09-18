# Memory ontology + agent memory facade — Design Spec

## Overview

This specification defines:

1. **Part B — Ontology:** a single grid to classify *any* storable unit (text files, posts, chat, logs, DHT shards, blobs, URLs) without exploding into dozens of incompatible types.
2. **Part C — Facade:** a stable **`MemoryPort`** contract and **pluggable adapters** so agents and orchestration code do not depend on Kademlia vs local disk vs HTTP.
3. **Part P — Principles:** simpler defaults, **self-extension** (new backends without core forks), **self-management** (policies, housekeeping), **self-sufficiency** (node works offline), **independence** (no mandatory third-party), and explicit **durability modes** so data is not lost or destroyed by accident.

Target codebase: **Immortal Swarm** (`DistributedMemory`, `MemoryBlock`, DHT + Reed–Solomon as in `architecture.md` and `docs/superpowers/specs/2026-05-12-immortal-swarm-design.md`).

## Non-goals (v1 of this spec)

- Full implementation of every adapter (S3, vector DB, Git, etc.).
- Legal/compliance review for caching third-party posts or personal data.
- Application-layer encryption for DHT payloads (only **document** “do not put raw secrets in shared memory”; encryption is a follow-up spec).
- Replacing existing `DistributedMemory` API in one step; v1 is **additive** (facade composes current store).

---

## Part P — Design principles

### P1. Simpler core

- One logical unit: **`Artifact`** + **`Ref`**; specialized behavior uses **tags** and **`attrs`** (versioned), not a growing enum of hard-coded Python types for every medium.
- **One ref surface** for routing: `ref:<scheme>:<opaque>` (examples: `ref:swarm:<block_id>`, `ref:file:<path>`, `ref:https:<url-encoded>` for read-mostly). Adapters register for a **`scheme`**.
- Ontology **axes** (Part B) are optional on each write: only what routing and policy need; sane defaults apply.

### P2. Self-extending

- **Adapter registry** keyed by `scheme`; adding a backend is **register + config**, not editing the facade’s core dispatch table in source (config lists enabled schemes and order).
- **`schema_version`** in artifact metadata for forward compatibility; unknown fields remain **opaque** to older nodes.
- **`capabilities()`** per adapter; the facade documents how it **aggregates** capabilities (e.g. union vs strict intersection for a given operation).

### P3. Self-managed

- **Per-node policies** (config): TTL for scratch, max size, which `block_type` / tags route to DHT vs local-only.
- **Background responsibilities** (conceptual; implementation later): shard health checks, RS repair when possible, scratch cleanup **only** for refs under `mutable scratch` / TTL policy.
- **Observability**: counters for put/get/errors/latency so memory is operable, not a black box.

### P4. Self-sufficient and independent

- **Local-first:** a node MUST remain functional with **only** `LocalScratchAdapter` (no network). DHT/RS is an **uplift**, not a hard dependency for all artifacts.
- External vendors (LLM APIs, social hosts) are **optional adapters**, never the root authority for the memory model.

### P5. Do not lose; do not destroy (explicit durability modes)

Policies are carried by metadata (tags and/or `attrs`), not implicit magic:

| Mode | Meaning |
|------|---------|
| **append-only / WORM** | New content gets a new `Ref` or new generation; previous refs are not overwritten (audit, final decisions). |
| **versioned** | Logical entity spans multiple refs; default read resolves to **latest** generation unless pinned. |
| **mutable scratch** | Overwrites and deletes allowed; subject to TTL and quotas. |
| **tombstone** | User-visible delete; index may retain minimal metadata/hash for replica consistency (adapter-defined). |
| **erasure (N-of-M)** | Network layer (existing RS + multi-node placement) improves survival against **node** loss; it does **not** remove the need for disk backup of **local** scratch if operators care about that disk. |

**`promote(ref)`** (facade-level): explicit transition from scratch / draft to durable network-backed storage (e.g. materialize a `MemoryBlock` in swarm and return new `ref:swarm:…`). Failures must be surfaced to the caller; no silent drop.

---

## Part B — Ontology (classification grid)

### Axes

1. **Carrier form:** blob | text | structured (e.g. msgpack/JSON) | stream (log, chat) | link (URL, logical pointer).
2. **Lifecycle:** ephemeral → session → durable → cold/archive.
3. **Addressing:** local path | URI | swarm block id | composite (e.g. repo + revision) — expressed as **`Ref`**.
4. **Trust / provenance:** human | agent | node | external source; truth vs signal-only.
5. **Access:** node-private | swarm-shared | public-read URL; metadata-only exposure where needed.
6. **Cost:** size, write churn, whether LLM interpretation is required for use.

### Pipeline roles (map to `block_type` and/or tags)

- **Raw** — scrapes, exports, dumps.
- **Working draft** — local notes, `.md`, editor buffers persisted to scratch.
- **Normalized knowledge** — facts, cards, rules.
- **Index** — tag → ids, embedding pointers (vectors may live in another adapter later).
- **Audit / evidence** — hashes, timestamps, source pointers.

### Examples on one grid

| Example | Form | Lifecycle | Address | Trust |
|---------|------|-----------|---------|-------|
| Note in `.txt` | text | durable (local) | `ref:file:…` | human/agent |
| Social post | link + optional cached blob | external + cache | `ref:https:…` | external |
| Swarm chat draft | stream / messages | session | thread/session id in attrs | agents |
| DHT + RS shard | binary fragment | durable (network) | `ref:swarm:…` | nodes |
| Parser log | stream / text | ephemeral → archive | file or log ref | agent |

---

## Part C — Facade: `MemoryPort` and adapters

### Contract (logical)

- **`put(artifact) → Ref`**
- **`get(ref) → Artifact`**
- **`exists(ref) → bool`**
- **`delete(ref) → bool`** (semantics depend on durability mode; tombstone where applicable)
- **`search(query) → list[RefMeta]`** — minimum: tags + `block_type`; full-text only if an adapter advertises it
- **`promote(ref) → Ref`** — optional for some deployments; required for “draft → durable swarm” flows
- **`capabilities() → Capabilities`**

### `Artifact` (minimum)

- Payload: `bytes | str`
- `mime` or coarse `kind`
- `tags: list[str]`
- `provenance: dict` (who, when, source)
- `attrs: dict` — includes `schema_version`, durability mode, optional generation links

### MVP adapters

1. **`DhtErasureAdapter`** (`scheme: swarm`) — wraps existing **`DistributedMemory`** + RS path; `Ref` = `ref:swarm:<block_id>` aligned with `MemoryBlock`.
2. **`LocalScratchAdapter`** (`scheme: file` or `local`) — node-local directory for drafts, caches, and plain-text notes; quotas + TTL policy.
3. **`LinkAdapter`** (`scheme: https` / `http`) — read-mostly; stores metadata + optional cached body in scratch per policy.

### Mapping to existing `MemoryBlock` / DHT

- **`MemoryBlock`** remains the canonical **network-serialized** block: `block_type`, `tags`, `content`, timestamps, TTL as today.
- Ontology axes and durability modes are reflected in **`attrs`** (msgpack) and/or **namespaced tags** (e.g. `dur:worm`, `dur:scratch`, `trust:external`) so legacy nodes that ignore unknown tags still work.
- **Routing defaults** (configurable): e.g. `dialog` / `task_result` → swarm; scraped raw HTML → local scratch + normalized knowledge block in swarm via `promote`.

### Errors

Stable error categories: backend unavailable, quota exceeded, ref not found, conflict (WORM overwrite attempt), external URL timeout, promote failure. No silent downgrade from durable to scratch without caller intent.

---

## Testing (spec-level)

- Unit tests per adapter in isolation (fake disk, mock Kademlia).
- Facade integration tests: two adapters + routing table + `promote`.
- Scenario table in test plan: text file → normalized swarm block; URL → cache + knowledge ref; chat session → optional archive promote.

---

## Verification (rerun)

| Date | Command | Result |
|------|---------|--------|
| 2026-05-13 | `pytest -q` (full suite) | 124 passed in 11.93s |

Spot-check vs this spec: `MemoryPort` + metrics (`swarm/memory/port.py`); MVP adapters `file` / `swarm` / `http`/`https`; `CompositeMemoryPort.promote` for `file`→`swarm`; optional `MemoryBlock.attrs` in DHT meta; WORM via `dur:worm` + `worm_base_ref` on `LocalScratchAdapter` (`WormConflictError`); `build_memory_port` + optional agent wire and `repair_shards_once` / `scan_and_repair_round` per implementation plan.

---

## Self-review (checklist)

1. **Placeholders:** none intentional; follow-up work is explicitly “non-goals” or “later”.
2. **Consistency:** ontology axes align with `MemoryPort` and `MemoryBlock`; RS is positioned as network resilience, not sole backup.
3. **Scope:** single spec covers B + C + principles; implementation can be phased.
4. **Ambiguity reduced:** durability modes and `promote` are named; ref format is single pattern.

---

## Approval

Design sections 1–3 and extension principles were approved in conversation (`+` / `+ в спек`).

**Recorded sign-off:** 2026-05-13 — user `+` after verification rerun; spec and implementation plan remain the source of truth for behavior.

**Implementation:** plan `docs/superpowers/plans/2026-05-13-memory-ontology-and-facade.md` — Phase 1 (Tasks 1–9) and Phase 2 (Tasks 10–12: WORM, agent wire, shard repair stub + background loop) are implemented in the codebase; re-run checks in **Verification (rerun)** above.
