# mDNS (LAN) + Chat Improvements — Design Spec

## Overview

Two coordinated upgrades for Immortal Swarm:

1. **mDNS on LAN** — optional discovery and advertisement of swarm nodes (Kademlia + Gossip + RPC ports) using Zeroconf, with **optional dependency** so the base install stays minimal.
2. **Chat improvements** — in order: **(a)** reliability and cost guards, **(b)** rolling summary and optional final summary for dialogue quality, **(c)** informational injection of recently discovered LAN peers into agent context when mDNS is available.

Target deployment: **mixed Windows and Linux** on one LAN; behavior should be identical in code paths, with clear logs when multicast or permissions block operation.

## Non-goals (v1)

- No automatic cross-node RPC from chat based on mDNS alone.
- No CAPTCHA or headless-browser workarounds for search engines.
- No change to trust model (still trust-all Phase 1).

---

## Part A — mDNS (LAN)

### Dependency policy

- **Base** `requirements.txt` does **not** add `zeroconf`.
- Optional install: `requirements-mdns.txt` containing `zeroconf>=0.132.0`, documented in README as `pip install -r requirements-mdns.txt`.
- Runtime: `try: import zeroconf` — if `ImportError`, mDNS features are **disabled** with a single `INFO` log at startup when `mdns.enabled` is true (and a warning that install is missing).

### Service advertisement

- **Service type:** `_immortal-swarm._tcp.local.` (override via `config.yaml` → `mdns.service_type` if needed later).
- **Instance name:** `ImmortalSwarm-<short_id>` where `<short_id>` is first 8 hex chars of Kademlia `node_id` (or random if id not yet known — implementation should register **after** `node_id` is assigned).
- **TXT record** (short keys, UTF-8 values where needed):

  | Key | Meaning |
  |-----|---------|
  | `v` | Protocol version, `1` |
  | `kid` | Kademlia node id (hex string) |
  | `kad` | Kademlia UDP port (integer string) |
  | `gos` | Gossip UDP port |
  | `rpc` | RPC TCP port |

Ports follow current `node.py` convention: `kad = port`, `gos = port + 1000`, `rpc = port + 2000` unless config later introduces explicit overrides (out of scope for v1).

### Discovery (browse)

- On node start, when `mdns.enabled` and zeroconf available: start **browse** for `_immortal-swarm._tcp.local.`.
- Maintain an in-memory **cache** of seen peers: `(host, kad_port, node_id?, last_seen)`.
- **Initial browse window:** configurable `mdns.initial_browse_seconds` (default **5**).
- **Periodic re-browse:** `mdns.refresh_interval_seconds` (default **60**), asyncio task cancelled on shutdown.
- **Bootstrap integration:** if `node.bootstrap` in YAML is empty and mDNS returns at least one peer, call `KademliaNode.start(bootstrap_addr=(host, kad_port))` for candidates in order until one succeeds or list exhausted; log each attempt.

### Lifecycle

- Register `ServiceInfo` **after** Kademlia listen succeeds; unregister on graceful shutdown.
- Windows/Linux: same code; document in README that **firewalls** must allow UDP 5353 and the app’s UDP/TCP ports.

### Config (`config.yaml`)

```yaml
mdns:
  enabled: false
  service_type: "_immortal-swarm._tcp.local."
  initial_browse_seconds: 5
  refresh_interval_seconds: 60
```

---

## Part B — Chat: reliability and cost (a)

### New `chat` keys

| Key | Default | Purpose |
|-----|---------|---------|
| `max_llm_calls_per_session` | `30` | Cap total `LLMRouter.complete` calls per user goal (interactive turn or one `task` run). |
| `selector_max_llm_calls` | `15` | Cap selector LLM calls when `selector: llm`; ignored for `round_robin`. |
| `max_context_chars` | `12000` | Truncate message history from the **start**, keeping the tail, before building agent prompt. |

Existing `max_rounds` and `done_keyword` remain.

### Semantics

- Counters increment on every successful dispatch to `complete` (agents + selector + summary calls defined in Part C count toward `max_llm_calls_per_session` unless spec below says otherwise — implementation should document exact accounting in code comments).
- When any cap is hit: end session with `finished_naturally=False`, set human-visible reason in `ChatDisplay.show_result` (e.g. `LLM call budget exhausted`, `Round limit`).
- On LLM failure inside `ChatRoom.step`: catch exceptions from `participant.respond`, append an agent-visible message such as `[ERROR] <short reason>`, **do not** crash CLI; optional single retry **off by default** (`chat.retry_failed_round: false`) to avoid doubling cost.

### Key pool exhaustion

- If `KeyPool.get_key` raises / router exhausts keys mid-session: stop gracefully with explicit message (reuse pattern from startup `ClickException` where appropriate).

---

## Part C — Chat: dialogue quality (b)

### Rolling summary

- `summary_every_n_agent_messages` — integer, default **0** (disabled). When `>0`, after every N **agent** messages (excluding the initial user goal), run one summarization `complete` with a compact bullet-only prompt; store `rolling_summary` on `ChatRoom`.
- `summary_model` — optional string; if absent, use **first** entry of `llm.models` as the cheap model for summaries.
- Prompt constraint: **do not invent facts** not present in the transcript slice being summarized.

### Prompt assembly

- `AgentParticipant.respond` receives tail history per `max_context_chars` **plus** `rolling_summary` prepended as a system or user block (implementation choice: single system addition `Rolling context: ...`).

### Final summary

- `final_summary` — bool, default `false`. When true, after session end, one short `complete` to produce 3–5 sentences «что решили / что осталось неясно», printed under `Итог` in `ChatDisplay`.

---

## Part D — Chat + LAN hints (c)

### Peer cache

- Reuse the mDNS browse cache populated in the **full node** process (`node.py start`).
- For **`node.py chat` / `node.py task`** without a full node: if `chat.lan_hints: true` **and** `mdns.enabled` **and** zeroconf importable, run a **browse-only** session for `mdns.initial_browse_seconds`, populate a local ephemeral cache, then close browser (no service registration).

### Injection into chat

- Once per user `goal` session, if cache non-empty: prepend to the **first** agent turn context a short plain-text block (max **10** lines):

  `LAN peers (mDNS, informational): <host:kad> ...`

- Agents must treat this as **hints only** (no claim that peers participate in the chat).

### Config

```yaml
chat:
  lan_hints: false
```

---

## Integration points

- **`node.py` `start_node`:** wire mDNS register + browse + bootstrap-from-mdns when enabled.
- **`node.py` `run_chat_interactive` / `run_task_oneshot`:** optional browse-only for LAN hints; apply chat limits and summaries inside `ChatRoom` / `AgentParticipant` per above.

### New module layout (implementation later)

- `swarm/network/mdns.py` — optional Zeroconf wrapper, `MDNSSwarm` or `SwarmMDNS` API: `start()`, `stop()`, `peers_snapshot() -> list[dict]`.
- Extend `swarm/chat/room.py` and `participant.py` for counters, truncation, summaries, LAN block.

---

## Testing strategy

- **mDNS:** unit tests with mocked `zeroconf` listener / fake `ServiceInfo` where possible; skip or mark integration tests that require real multicast in CI.
- **Chat:** unit tests for truncation, counter caps, summary trigger every N messages, error path inserts `[ERROR]` without raising.

---

## Self-review (spec)

- No open TBD markers; `zeroconf` minimum version stated above.
- Parts B–D depend on Part A only for LAN hints; core chat limits work without mDNS.
- Scope is one implementation plan candidate; parser work remains deferred per user.
