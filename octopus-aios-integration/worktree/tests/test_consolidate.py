"""Tests for swarm.memory.consolidate -- GC + dedup planner."""

from __future__ import annotations

import pytest

from swarm.memory.consolidate import (
    ConsolidationReport,
    Consolidator,
    _content_hash,
    _jaccard,
    _shingles,
)
from swarm.memory.port import MemoryMetrics
from swarm.memory.repository import MemoryRepository
from swarm.memory.types import Artifact, Capabilities, RefMeta

# ---------------------------------------------------------------------------
# Fake port
# ---------------------------------------------------------------------------


class FakePort:
    def __init__(self) -> None:
        self._store: dict[str, Artifact] = {}
        self._metrics = MemoryMetrics()
        self.delete_fails: set[str] = set()

    @property
    def metrics(self):
        return self._metrics

    def capabilities(self):
        return Capabilities(
            schemes=frozenset({"file"}),
            supports_search=True,
            supports_delete=True,
            supports_promote=False,
        )

    async def put(self, art: Artifact) -> str:
        ref = f"ref:file:{len(self._store)}"
        self._store[ref] = art
        return ref

    async def get(self, ref):
        return self._store[ref]

    async def exists(self, ref):
        return ref in self._store

    async def delete(self, ref):
        if ref in self.delete_fails:
            return False
        return self._store.pop(ref, None) is not None

    async def search(self, tags, owner=None):
        return [
            RefMeta(ref=r, scheme="file", tags=list(a.tags))
            for r, a in self._store.items()
            if all(t in (a.tags or []) for t in (tags or []))
        ]


@pytest.fixture
def port():
    return FakePort()


@pytest.fixture
def repo(port):
    return MemoryRepository(port)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_content_hash_ignores_timestamps():
    h1 = _content_hash({"text": "x"}, {"_table": "t", "_ts": 1.0})
    h2 = _content_hash({"text": "x"}, {"_table": "t", "_ts": 999.0})
    assert h1 == h2


def test_content_hash_differs_when_payload_differs():
    h1 = _content_hash({"text": "alpha"})
    h2 = _content_hash({"text": "beta"})
    assert h1 != h2


def test_shingles_handles_short_strings():
    assert _shingles("abc", k=4) == {"abc"}
    assert _shingles("", k=4) == set()


def test_jaccard_basics():
    assert _jaccard(set(), set()) == 0.0
    assert _jaccard({"a"}, {"a"}) == 1.0
    assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# plan -- stale by TTL
# ---------------------------------------------------------------------------


async def test_plan_flags_stale_rows(repo):
    now = 1_000_000.0
    await repo.save({"x": 1}, table="notes", attrs={"_ts": now - 10_000})
    await repo.save({"x": 2}, table="notes", attrs={"_ts": now - 100})

    consolidator = Consolidator(repo)
    report = await consolidator.plan(ttl_seconds=1_000, now=now)
    assert len(report.stale) == 1
    assert report.total == 2


async def test_plan_no_ttl_means_no_stale(repo):
    await repo.save({"x": 1}, table="notes")
    consolidator = Consolidator(repo)
    report = await consolidator.plan()
    assert report.stale == []


# ---------------------------------------------------------------------------
# plan -- exact duplicates
# ---------------------------------------------------------------------------


async def test_plan_groups_exact_duplicates(repo):
    await repo.save({"text": "hello"}, table="notes", attrs={"_ts": 1.0})
    await repo.save({"text": "hello"}, table="notes", attrs={"_ts": 2.0})
    await repo.save({"text": "hello"}, table="notes", attrs={"_ts": 3.0})
    await repo.save({"text": "different"}, table="notes")

    consolidator = Consolidator(repo)
    report = await consolidator.plan()
    assert len(report.duplicates) == 1
    assert len(report.duplicates[0]) == 3


async def test_plan_does_not_dedupe_across_tables(repo):
    await repo.save({"text": "x"}, table="notes")
    await repo.save({"text": "x"}, table="logs")
    consolidator = Consolidator(repo)
    report = await consolidator.plan()
    assert report.duplicates == []


# ---------------------------------------------------------------------------
# plan -- near duplicates
# ---------------------------------------------------------------------------


async def test_plan_finds_near_duplicates(repo):
    await repo.save({"text": "hello world how are you today friend"}, table="chat")
    await repo.save({"text": "hello world how are you today friends"}, table="chat")
    await repo.save({"text": "totally unrelated payload about lemons"}, table="chat")

    consolidator = Consolidator(repo)
    report = await consolidator.plan(near_threshold=0.8)
    assert len(report.near_duplicates) == 1
    assert len(report.near_duplicates[0]) == 2


async def test_plan_skips_near_duplicate_if_exact_already(repo):
    await repo.save({"text": "identical"}, table="t")
    await repo.save({"text": "identical"}, table="t")
    consolidator = Consolidator(repo)
    report = await consolidator.plan(near_threshold=0.5)
    assert len(report.duplicates) == 1
    assert report.near_duplicates == []


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


async def test_apply_deletes_stale(repo, port):
    now = 1_000_000.0
    await repo.save({"x": 1}, table="notes", attrs={"_ts": now - 10_000})
    keep = await repo.save({"x": 2}, table="notes", attrs={"_ts": now - 10})

    consolidator = Consolidator(repo)
    report = await consolidator.plan(ttl_seconds=1_000, now=now)
    await consolidator.apply(report)

    assert len(report.deletions) == 1
    assert await port.exists(keep) is True


async def test_apply_keeps_newest_dup_and_deletes_older(repo, port):
    a = await repo.save({"text": "dup"}, table="t", attrs={"_ts": 1.0})
    b = await repo.save({"text": "dup"}, table="t", attrs={"_ts": 2.0})
    c = await repo.save({"text": "dup"}, table="t", attrs={"_ts": 3.0})

    consolidator = Consolidator(repo)
    report = await consolidator.plan()
    await consolidator.apply(report)

    assert await port.exists(c) is True
    assert await port.exists(a) is False
    assert await port.exists(b) is False
    assert set(report.deletions) == {a, b}


async def test_apply_records_deletion_failures(repo, port):
    a = await repo.save({"text": "dup"}, table="t", attrs={"_ts": 1.0})
    b = await repo.save({"text": "dup"}, table="t", attrs={"_ts": 2.0})

    port.delete_fails.add(a)
    consolidator = Consolidator(repo)
    report = await consolidator.plan()
    await consolidator.apply(report)

    assert a in report.deletion_failed
    assert b not in report.deletions  # b survives as newest


async def test_apply_near_duplicates_off_by_default(repo, port):
    a = await repo.save({"text": "hello world friend"}, table="chat", attrs={"_ts": 1.0})
    b = await repo.save({"text": "hello world friends"}, table="chat", attrs={"_ts": 2.0})

    consolidator = Consolidator(repo)
    report = await consolidator.plan(near_threshold=0.5)
    await consolidator.apply(report)

    assert await port.exists(a) is True
    assert await port.exists(b) is True
    assert report.deletions == []


async def test_apply_near_duplicates_when_enabled(repo, port):
    a = await repo.save({"text": "hello world friend"}, table="chat", attrs={"_ts": 1.0})
    b = await repo.save({"text": "hello world friends"}, table="chat", attrs={"_ts": 2.0})

    consolidator = Consolidator(repo)
    report = await consolidator.plan(near_threshold=0.5)
    await consolidator.apply(report, delete_near_duplicates=True)

    assert await port.exists(a) is False
    assert await port.exists(b) is True


# ---------------------------------------------------------------------------
# Report serialisation
# ---------------------------------------------------------------------------


def test_consolidation_report_to_dict_summary_counts():
    r = ConsolidationReport(
        total=5,
        stale=["a"],
        duplicates=[["b", "c", "d"]],
        near_duplicates=[["e", "f"]],
    )
    d = r.to_dict()
    assert d["summary"]["stale_count"] == 1
    assert d["summary"]["duplicate_groups"] == 1
    assert d["summary"]["near_duplicate_groups"] == 1
    # would_delete = 1 stale + (3-1) extra duplicates = 3
    assert d["summary"]["would_delete"] == 3


async def test_plan_empty_repo_returns_zero_report(repo):
    consolidator = Consolidator(repo)
    report = await consolidator.plan(ttl_seconds=1.0)
    assert report.total == 0
    assert report.stale == []
    assert report.duplicates == []
