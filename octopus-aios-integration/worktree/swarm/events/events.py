"""Typed events for the swarm EventBus.

All events are frozen dataclasses so they are hashable and safe to
publish across concurrent subscribers.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Tasks ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TaskCreated:
    task_id: str


@dataclass(frozen=True)
class TaskCompleted:
    task_id: str
    result_ref: str


@dataclass(frozen=True)
class TaskFailed:
    task_id: str
    error: str


# ── Blocks (erasure-coded memory) ─────────────────────────────────

@dataclass(frozen=True)
class BlockStored:
    block_id: str


@dataclass(frozen=True)
class BlockRetrieved:
    block_id: str


# ── Node lifecycle ────────────────────────────────────────────────

@dataclass(frozen=True)
class NodeJoined:
    node_id: str


@dataclass(frozen=True)
class NodeLeft:
    node_id: str


# ── NEW: Gossip ───────────────────────────────────────────────────

@dataclass(frozen=True)
class GossipReceived:
    """Fired when a gossip message arrives (after dedup)."""
    msg_id: str
    msg_type: str
    from_addr: str = ""


@dataclass(frozen=True)
class GossipSent:
    """Fired when a gossip round sends messages."""
    msg_count: int
    target_count: int


# ── NEW: Memory facade ───────────────────────────────────────────

@dataclass(frozen=True)
class MemoryPut:
    """Fired after a successful put on any adapter."""
    scheme: str
    ref: str
    size_bytes: int = 0


@dataclass(frozen=True)
class MemoryGetOk:
    """Fired after a successful get."""
    scheme: str
    ref: str
    size_bytes: int = 0


@dataclass(frozen=True)
class MemoryGetFailed:
    """Fired when a get fails."""
    scheme: str
    ref: str
    error: str


# ── NEW: LLM ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class LLMCallStarted:
    model: str
    base_url: str = ""


@dataclass(frozen=True)
class LLMCallCompleted:
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    base_url: str = ""


@dataclass(frozen=True)
class LLMCallFailed:
    model: str
    error: str
    attempt: int = 0
    base_url: str = ""


# ── NEW: Shard repair ────────────────────────────────────────────

@dataclass(frozen=True)
class ShardRepairStarted:
    block_id: str


@dataclass(frozen=True)
class ShardRepairCompleted:
    block_id: str
    shards_recovered: int


@dataclass(frozen=True)
class ShardRepairFailed:
    block_id: str
    error: str


# ── NEW: Peer discovery ──────────────────────────────────────────

@dataclass(frozen=True)
class PeerDiscovered:
    host: str
    port: int
    via: str = "kademlia"  # "kademlia" | "mdns" | "gossip" | "bootstrap"


# ── NEW: Config ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ConfigReloaded:
    changed_keys: tuple[str, ...] = ()


# ── NEW: Adapter health ─────────────────────────────────────────

@dataclass(frozen=True)
class AdapterHealthChanged:
    scheme: str
    status: str = "healthy"  # "healthy" | "degraded" | "down"
    reason: str = ""
