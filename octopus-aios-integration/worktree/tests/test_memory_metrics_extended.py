"""Extended-metrics + DB-helper tests for the memory facade."""

from __future__ import annotations

import asyncio

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.port import MemoryMetrics
from swarm.memory.repository import MemoryRepository
from swarm.memory.types import Artifact, MemoryAdapterError

# ---------------------------------------------------------------------------
# MemoryMetrics direct unit tests
# ---------------------------------------------------------------------------

def test_metrics_records_latency_and_returns_percentiles():
    m = MemoryMetrics()
    for ms in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        m.record_latency("file", "put", ms / 1000.0)
    p50 = m.percentile("file", "put", 0.5)
    p95 = m.percentile("file", "put", 0.95)
    assert p50 is not None and 0.04 <= p50 <= 0.06
    assert p95 is not None and p95 >= 0.09


def test_metrics_availability_defaults_one_when_unused():
    m = MemoryMetrics()
    assert m.availability("nullpointer") == 1.0


def test_metrics_availability_reflects_get_outcomes():
    m = MemoryMetrics()
    for _ in range(7):
        m.record_get("dpaste", ok=True)
    for _ in range(3):
        m.record_get("dpaste", ok=False)
    assert m.availability("dpaste") == 0.7


def test_metrics_records_bytes_only_positive():
    m = MemoryMetrics()
    m.record_bytes_in("catbox", 100)
    m.record_bytes_in("catbox", 0)
    m.record_bytes_in("catbox", -5)
    assert m.bytes_in["catbox"] == 100


def test_metrics_snapshot_contains_all_observed_schemes():
    m = MemoryMetrics()
    m.record_put("file")
    m.record_get("dpaste", ok=False)
    m.record_bytes_out("ixio", 32)
    snap = m.snapshot()
    assert set(snap.keys()) == {"file", "dpaste", "ixio"}
    assert snap["dpaste"]["gets_err"] == 1
    assert snap["ixio"]["bytes_out"] == 32


def test_metrics_sample_buffer_is_bounded():
    m = MemoryMetrics()
    for _ in range(MemoryMetrics._max_samples + 50):
        m.record_latency("file", "put", 0.001)
    samples = m._lat_samples[("file", "put")]
    assert len(samples) == MemoryMetrics._max_samples


# ---------------------------------------------------------------------------
# CompositeMemoryPort: metrics actually fire on put/get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_composite_records_latency_and_bytes(tmp_path):
    adapter = LocalScratchAdapter(tmp_path)
    port = CompositeMemoryPort({"file": adapter})
    payload = b"X" * 1024
    ref = await port.put(Artifact(content=payload))
    art = await port.get(ref)
    assert art.content == payload

    m = port.metrics
    assert m.puts["file"] == 1
    assert m.gets_ok["file"] == 1
    assert m.bytes_out["file"] == 1024
    assert m.bytes_in["file"] == 1024
    assert m.percentile("file", "put", 0.5) is not None
    assert m.availability("file") == 1.0


@pytest.mark.asyncio
async def test_composite_records_error_on_unknown_scheme(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    with pytest.raises(MemoryAdapterError):
        await port.get("ref:nope:xx")
    snap = port.metrics.snapshot()
    assert snap["nope"]["gets_err"] == 1
    assert "no adapter registered" in snap["nope"]["last_error"]


# ---------------------------------------------------------------------------
# Repository: count / distinct / latest / delete
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    return MemoryRepository(port), port


@pytest.mark.asyncio
async def test_repo_count_matches_query(repo):
    r, _ = repo
    await r.save({"name": "a", "p": 1}, table="parts")
    await r.save({"name": "b", "p": 2}, table="parts")
    await r.save({"name": "c"}, table="other")
    assert await r.count(table="parts") == 2
    assert await r.count() == 3


@pytest.mark.asyncio
async def test_repo_distinct_unique_values(repo):
    r, _ = repo
    await r.save({"v": "x"}, table="t", attrs={"author": "lisa"})
    await r.save({"v": "y"}, table="t", attrs={"author": "lisa"})
    await r.save({"v": "z"}, table="t", attrs={"author": "vasily"})
    authors = await r.distinct("attrs.author", table="t")
    assert sorted(authors) == ["lisa", "vasily"]
    vs = await r.distinct("data.v", table="t")
    assert sorted(vs) == ["x", "y", "z"]


@pytest.mark.asyncio
async def test_repo_distinct_rejects_bad_path(repo):
    r, _ = repo
    with pytest.raises(ValueError):
        await r.distinct("invalid.path")


@pytest.mark.asyncio
async def test_repo_latest_orders_by_ts(repo):
    r, _ = repo
    await r.save({"n": 1}, table="t")
    await asyncio.sleep(0.005)
    await r.save({"n": 2}, table="t")
    await asyncio.sleep(0.005)
    await r.save({"n": 3}, table="t")
    last2 = await r.latest(table="t", n=2)
    assert [row.data["n"] for row in last2] == [3, 2]


@pytest.mark.asyncio
async def test_repo_delete_round_trip(repo):
    r, _ = repo
    ref = await r.save({"n": 1}, table="t")
    assert await r.count(table="t") == 1
    assert await r.delete(ref) is True
    assert await r.count(table="t") == 0
