"""Smart routing tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.port import MemoryMetrics
from swarm.memory.routing import (
    SmartReplicator,
    rank_schemes,
    score,
    select_top,
)
from swarm.memory.types import Artifact, Capabilities, MemoryAdapterError


class _FakeAdapter:
    """Adapter with controllable success/failure behaviour."""

    def __init__(self, scheme: str, *, fail: bool = False, slow: float = 0.0) -> None:
        self.scheme = scheme
        self.fail = fail
        self.slow = slow
        self.calls = 0

    async def put(self, artifact):
        self.calls += 1
        if self.slow:
            import asyncio as _asyncio
            await _asyncio.sleep(self.slow)
        if self.fail:
            raise RuntimeError(f"{self.scheme} broken")
        return f"ref:{self.scheme}:{self.calls}"

    async def get(self, ref):
        raise NotImplementedError

    async def exists(self, ref):
        return False

    async def delete(self, ref):
        return False

    async def search(self, tags, owner):
        return []

    def capabilities(self):
        return Capabilities(
            schemes=frozenset({self.scheme}),
            supports_search=False,
            supports_delete=False,
            supports_promote=False,
        )


# ---------------------------------------------------------------------------
# score()
# ---------------------------------------------------------------------------

def test_score_optimistic_for_unobserved_scheme():
    m = MemoryMetrics()
    s = score("brand-new", m)
    assert s.availability == 1.0
    assert s.score > 0.5  # close to 1.0


def test_score_drops_with_failures():
    m = MemoryMetrics()
    for _ in range(8):
        m.record_get("good", ok=True)
    for _ in range(8):
        m.record_get("bad", ok=False)
    s_good = score("good", m)
    s_bad = score("bad", m)
    assert s_good.score > s_bad.score


def test_score_penalises_high_latency():
    m = MemoryMetrics()
    for ms in [50] * 10:
        m.record_latency("fast", "put", ms / 1000)
    for ms in [3000] * 10:
        m.record_latency("slow", "put", ms / 1000)
    assert score("fast", m).score > score("slow", m).score


# ---------------------------------------------------------------------------
# rank / select
# ---------------------------------------------------------------------------

def test_rank_schemes_orders_desc_by_score():
    m = MemoryMetrics()
    for _ in range(5):
        m.record_get("strong", ok=True)
    for _ in range(5):
        m.record_get("weak", ok=False)
    ranked = rank_schemes(["weak", "strong", "neutral"], m)
    ordering = [r.scheme for r in ranked]
    # neutral (no data, score=1.0) and strong both tie ≈ 1.0; weak last.
    assert ordering[-1] == "weak"
    assert "strong" in ordering[:2] and "neutral" in ordering[:2]


def test_select_top_returns_k_or_fewer():
    m = MemoryMetrics()
    chosen = select_top(["a", "b", "c", "d"], m, k=2)
    assert len(chosen) == 2
    # All scores equal -> alphabetical tiebreaker.
    assert chosen == ["a", "b"]


def test_select_top_handles_negative_k():
    m = MemoryMetrics()
    assert select_top(["a", "b"], m, k=-3) == []


# ---------------------------------------------------------------------------
# SmartReplicator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smart_replicator_picks_top_k_by_score(tmp_path: Path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "fast": _FakeAdapter("fast"),
            "medium": _FakeAdapter("medium"),
            "slow": _FakeAdapter("slow"),
        }
    )
    # Prime metrics: slow has many failures, fast has many ok gets.
    for _ in range(10):
        port.metrics.record_get("fast", ok=True)
    for _ in range(8):
        port.metrics.record_get("slow", ok=False)

    rep = SmartReplicator(port)
    outcomes = await rep.smart_replicate(Artifact(content=b"x"), k=2)
    successful = {o.scheme for o in outcomes if o.ok}
    # slow should NOT be in the first wave.
    assert "slow" not in successful
    assert "fast" in successful


@pytest.mark.asyncio
async def test_smart_replicator_falls_back_when_top_fails(tmp_path: Path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "broken_top": _FakeAdapter("broken_top", fail=True),
            "alt_a": _FakeAdapter("alt_a"),
            "alt_b": _FakeAdapter("alt_b"),
        }
    )
    rep = SmartReplicator(port)
    outcomes = await rep.smart_replicate(
        Artifact(content=b"x"), k=1, min_replicas=1
    )
    successful = [o for o in outcomes if o.ok]
    # broken_top fails, fallback wave must produce at least 1 success.
    assert successful, outcomes


@pytest.mark.asyncio
async def test_smart_replicator_respects_forbid_set(tmp_path: Path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "censored": _FakeAdapter("censored"),
            "ok": _FakeAdapter("ok"),
        }
    )
    rep = SmartReplicator(port)
    outcomes = await rep.smart_replicate(
        Artifact(content=b"x"),
        k=2,
        forbid={"file", "censored"},
    )
    used = {o.scheme for o in outcomes}
    assert "censored" not in used
    assert "file" not in used


@pytest.mark.asyncio
async def test_smart_replicator_budget_caps_attempts(tmp_path: Path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "a": _FakeAdapter("a", fail=True),
            "b": _FakeAdapter("b", fail=True),
            "c": _FakeAdapter("c", fail=True),
            "d": _FakeAdapter("d"),  # would succeed, but budget=2 caps us out
        }
    )
    rep = SmartReplicator(port)
    outcomes = await rep.smart_replicate(
        Artifact(content=b"x"), k=2, min_replicas=3, budget=2
    )
    assert len(outcomes) == 2


@pytest.mark.asyncio
async def test_smart_replicator_raises_when_pool_empty(tmp_path: Path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    rep = SmartReplicator(port)
    with pytest.raises(MemoryAdapterError):
        await rep.smart_replicate(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_smart_replicator_uses_candidate_pool_subset(tmp_path: Path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "alpha": _FakeAdapter("alpha"),
            "beta": _FakeAdapter("beta"),
            "gamma": _FakeAdapter("gamma"),
        }
    )
    rep = SmartReplicator(port)
    outcomes = await rep.smart_replicate(
        Artifact(content=b"x"),
        k=2,
        candidate_pool=["alpha", "beta"],
    )
    used = {o.scheme for o in outcomes}
    assert used <= {"alpha", "beta"}


@pytest.mark.asyncio
async def test_smart_replicator_stops_early_when_min_replicas_reached(tmp_path: Path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "a": _FakeAdapter("a"),
            "b": _FakeAdapter("b"),
            "c": _FakeAdapter("c"),
            "d": _FakeAdapter("d"),
        }
    )
    rep = SmartReplicator(port)
    outcomes = await rep.smart_replicate(
        Artifact(content=b"x"), k=2, min_replicas=2
    )
    # Two parallel puts hit success target -> no further waves.
    assert len([o for o in outcomes if o.ok]) >= 2
    # Did not waste calls on c/d (since k=2 went through and succeeded).
    schemes_called = {o.scheme for o in outcomes}
    assert len(schemes_called) == 2
