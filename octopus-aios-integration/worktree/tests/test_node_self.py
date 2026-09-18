"""
tests/test_node_self.py
────────────────────────
Тесты NodeSelf (самоосознание ноды).
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.immortal.node_self import (
    HealthStatus,
    LoadSnapshot,
    NodeRole,
    NodeSelf,
    NodeSnapshot,
    SkillDescriptor,
)


# ════════════════════════════════════════════════════════════════════════════
# Фикстуры
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def ns():
    node = NodeSelf(node_id="test-node", role=NodeRole.HYBRID)
    node.register_skill(SkillDescriptor(name="web_parser"))
    node.register_skill(SkillDescriptor(name="note_search", capacity=2))
    return node


@pytest.fixture()
def mock_gossip():
    g = MagicMock()
    g.inject = AsyncMock()
    g._peers = [("127.0.0.1", 9001)]
    return g


# ════════════════════════════════════════════════════════════════════════════
# SkillDescriptor
# ════════════════════════════════════════════════════════════════════════════

def test_register_skill(ns):
    assert ns.has_skill("web_parser")
    assert ns.has_skill("note_search")
    assert not ns.has_skill("unknown_skill")


def test_register_skill_no_duplicates(ns):
    ns.register_skill(SkillDescriptor(name="web_parser"))
    ns.register_skill(SkillDescriptor(name="web_parser"))
    count = sum(1 for s in ns._skills if s.name == "web_parser")
    assert count == 1


def test_unregister_skill(ns):
    ns.unregister_skill("web_parser")
    assert not ns.has_skill("web_parser")
    assert ns.has_skill("note_search")


# ════════════════════════════════════════════════════════════════════════════
# Health score
# ════════════════════════════════════════════════════════════════════════════

def test_health_healthy(ns):
    load  = LoadSnapshot(tasks_pending=0, cpu_percent=10)
    score, status = ns._compute_health(load)
    assert score >= 0.8
    assert status == HealthStatus.HEALTHY


def test_health_degraded_pending(ns):
    load  = LoadSnapshot(tasks_pending=25, cpu_percent=20)  # updated: 25>20 -> score-=0.4 -> DEGRADED
    score, status = ns._compute_health(load)
    assert status in (HealthStatus.DEGRADED, HealthStatus.OVERLOADED)


def test_health_overloaded(ns):
    load  = LoadSnapshot(tasks_pending=25, cpu_percent=95)
    score, status = ns._compute_health(load)
    assert score < 0.5
    assert status in (HealthStatus.OVERLOADED, HealthStatus.DYING)


def test_health_score_clamped(ns):
    load  = LoadSnapshot(tasks_pending=100, cpu_percent=100, ram_mb=2048)
    score, _ = ns._compute_health(load)
    assert 0.0 <= score <= 1.0


# ════════════════════════════════════════════════════════════════════════════
# NodeSnapshot
# ════════════════════════════════════════════════════════════════════════════

def test_snapshot_fields(ns):
    snap = ns.snapshot(LoadSnapshot())
    assert snap.node_id == "test-node"
    assert snap.role    == NodeRole.HYBRID.value
    assert len(snap.skills) == 2
    assert snap.uptime_sec  >= 0
    assert snap.version     == NodeSelf.VERSION
    assert isinstance(snap.health_score, float)


def test_snapshot_to_payload(ns):
    snap    = ns.snapshot(LoadSnapshot())
    payload = snap.to_payload()
    assert isinstance(payload, dict)
    assert "node_id"      in payload
    assert "skills"       in payload
    assert "health_score" in payload
    assert "load"         in payload


# ════════════════════════════════════════════════════════════════════════════
# Gossip broadcast
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_broadcast_injects_gossip(ns, mock_gossip):
    ns._gossip = mock_gossip
    await ns.broadcast(LoadSnapshot())
    mock_gossip.inject.assert_called_once()
    msg = mock_gossip.inject.call_args[0][0]
    assert msg.msg_type == "NODE_AWARENESS"
    assert msg.payload["node_id"] == "test-node"


@pytest.mark.asyncio
async def test_broadcast_no_gossip(ns):
    """Без gossip не должно падать."""
    await ns.broadcast(LoadSnapshot())  # ns._gossip is None


# ════════════════════════════════════════════════════════════════════════════
# handle_gossip (входящий awareness от пира)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_handle_gossip_adds_to_map(ns):
    from swarm.network.gossip import GossipMessage
    snap = NodeSnapshot(
        node_id="peer-1", role="worker",
        skills=[{"name": "web_parser", "version": "1.0", "capacity": 1, "description": ""}],
        health="healthy", health_score=0.9,
        load={}, uptime_sec=100, version="0.1",
        platform_info="Linux", spawned_by="",
    )
    msg = GossipMessage(msg_type="NODE_AWARENESS", payload=snap.to_payload())
    await ns.handle_gossip(msg)
    assert "peer-1" in ns.swarm_map()


@pytest.mark.asyncio
async def test_handle_gossip_ignores_self(ns):
    from swarm.network.gossip import GossipMessage
    snap = NodeSnapshot(
        node_id="test-node",  # тот же что у ns
        role="worker", skills=[], health="healthy",
        health_score=1.0, load={}, uptime_sec=10,
        version="0.1", platform_info="", spawned_by="",
    )
    msg = GossipMessage(msg_type="NODE_AWARENESS", payload=snap.to_payload())
    await ns.handle_gossip(msg)
    # Себя не добавляем
    assert "test-node" not in ns.swarm_map()


@pytest.mark.asyncio
async def test_handle_gossip_ignores_other_types(ns):
    from swarm.network.gossip import GossipMessage
    msg = GossipMessage(msg_type="TASK_BROADCAST", payload={"id": "t1"})
    await ns.handle_gossip(msg)
    assert len(ns.swarm_map()) == 0


# ════════════════════════════════════════════════════════════════════════════
# Карта роя
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_find_nodes_with_skill(ns):
    from swarm.network.gossip import GossipMessage

    for nid, skill in [("p1", "web_parser"), ("p2", "local_llm"), ("p3", "web_parser")]:
        snap = NodeSnapshot(
            node_id=nid, role="worker",
            skills=[{"name": skill, "version": "1.0", "capacity": 1, "description": ""}],
            health="healthy", health_score=0.9,
            load={}, uptime_sec=10, version="0.1",
            platform_info="", spawned_by="",
        )
        await ns.handle_gossip(GossipMessage("NODE_AWARENESS", snap.to_payload()))

    parsers = ns.find_nodes_with_skill("web_parser")
    assert len(parsers) == 2
    assert all(
        any(s.get("name") == "web_parser" for s in p.skills)
        for p in parsers
    )


def test_find_healthiest(ns):
    from swarm.immortal.node_self import NodeSnapshot
    for nid, score in [("a", 0.9), ("b", 0.3), ("c", 0.7)]:
        ns._swarm_map[nid] = NodeSnapshot(
            node_id=nid, role="worker", skills=[],
            health="healthy", health_score=score,
            load={}, uptime_sec=10, version="0.1",
            platform_info="", spawned_by="",
        )
    top = ns.find_healthiest(2)
    assert len(top) == 2
    assert top[0].node_id == "a"
    assert top[1].node_id == "c"


def test_prune_stale(ns):
    old_time = time.time() - 200
    ns._swarm_map["stale"] = NodeSnapshot(
        node_id="stale", role="worker", skills=[],
        health="dying", health_score=0.1,
        load={}, uptime_sec=200, version="0.1",
        platform_info="", spawned_by="", ts=old_time,
    )
    ns._swarm_map["fresh"] = NodeSnapshot(
        node_id="fresh", role="worker", skills=[],
        health="healthy", health_score=0.9,
        load={}, uptime_sec=10, version="0.1",
        platform_info="", spawned_by="",
    )
    pruned = ns.prune_stale(ttl=120)
    assert pruned == 1
    assert "stale" not in ns.swarm_map()
    assert "fresh" in ns.swarm_map()


# ════════════════════════════════════════════════════════════════════════════
# stats()
# ════════════════════════════════════════════════════════════════════════════

def test_stats_structure(ns):
    s = ns.stats()
    assert "node_id"        in s
    assert "role"           in s
    assert "skills"         in s
    assert "health"         in s
    assert "health_score"   in s
    assert "uptime_sec"     in s
    assert "swarm_map_size" in s
    assert "known_roles"    in s
    assert "known_skills"   in s
    assert "web_parser"     in s["skills"]
