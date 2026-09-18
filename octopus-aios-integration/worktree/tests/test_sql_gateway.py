"""Tests for swarm.memory.sql_gateway -- SQLite mirror of MemoryRepository."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from swarm.memory.port import MemoryMetrics
from swarm.memory.repository import MemoryRepository
from swarm.memory.sql_gateway import SqlMirror
from swarm.memory.types import Artifact, Capabilities, RefMeta

# ---------------------------------------------------------------------------
# Fake memory port for the repository
# ---------------------------------------------------------------------------


class FakePort:
    def __init__(self) -> None:
        self._store: dict[str, Artifact] = {}
        self._metrics = MemoryMetrics()

    @property
    def metrics(self) -> MemoryMetrics:
        return self._metrics

    def capabilities(self) -> Capabilities:
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

    async def get(self, ref: str) -> Artifact:
        return self._store[ref]

    async def exists(self, ref: str) -> bool:
        return ref in self._store

    async def delete(self, ref: str) -> bool:
        return self._store.pop(ref, None) is not None

    async def search(self, tags, owner=None):
        return [
            RefMeta(ref=ref, scheme="file", tags=list(a.tags))
            for ref, a in self._store.items()
            if all(t in (a.tags or []) for t in (tags or []))
        ]


@pytest.fixture
def repo():
    return MemoryRepository(FakePort())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_open_memory_creates_schema():
    mirror = SqlMirror.open_memory()
    rows = mirror.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = [r["name"] for r in rows]
    assert "records" in names
    assert "record_tags" in names
    mirror.close()


def test_open_creates_parent_dirs(tmp_path: Path):
    db_path = tmp_path / "nested" / "deeper" / "mirror.db"
    mirror = SqlMirror.open(db_path)
    assert db_path.exists()
    mirror.close()


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


async def test_sync_mirrors_every_row(repo):
    await repo.save({"x": 1}, table="notes", tags=["a"])
    await repo.save({"x": 2}, table="notes", tags=["a", "b"])
    await repo.save({"y": 3}, table="logs")

    mirror = SqlMirror.open_memory()
    written = await mirror.sync(repo)
    assert written == 3
    assert mirror.count_records() == 3
    mirror.close()


async def test_sync_populates_table_name_and_ts(repo):
    await repo.save({"x": 1}, table="notes")

    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    rows = mirror.fetchall("SELECT ref, table_name, ts FROM records")
    assert len(rows) == 1
    assert rows[0]["table_name"] == "notes"
    assert rows[0]["ts"] is not None
    assert rows[0]["ts"] <= time.time() + 1
    mirror.close()


async def test_sync_populates_tags_table(repo):
    await repo.save({"x": 1}, table="notes", tags=["alpha", "beta"])

    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    tags = mirror.fetchall("SELECT tag FROM record_tags ORDER BY tag")
    tag_names = [t["tag"] for t in tags]
    assert "alpha" in tag_names
    assert "beta" in tag_names
    assert "table:notes" in tag_names
    mirror.close()


async def test_sync_stores_json_blobs(repo):
    await repo.save(
        {"name": "Vasya", "age": 30},
        table="users",
        attrs={"custom": "value"},
    )

    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    row = mirror.fetchall("SELECT attrs_json, data_json FROM records")[0]
    data = json.loads(row["data_json"])
    attrs = json.loads(row["attrs_json"])
    assert data == {"name": "Vasya", "age": 30}
    assert attrs.get("custom") == "value"
    assert attrs.get("_table") == "users"
    mirror.close()


async def test_sync_is_idempotent_rebuild(repo):
    await repo.save({"x": 1}, table="notes")
    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    assert mirror.count_records() == 1

    await repo.save({"x": 2}, table="notes")
    await mirror.sync(repo)
    assert mirror.count_records() == 2
    mirror.close()


async def test_sync_empty_repo_creates_empty_mirror(repo):
    mirror = SqlMirror.open_memory()
    written = await mirror.sync(repo)
    assert written == 0
    assert mirror.count_records() == 0
    mirror.close()


# ---------------------------------------------------------------------------
# Convenience reads
# ---------------------------------------------------------------------------


async def test_tables_returns_distinct(repo):
    await repo.save({}, table="notes")
    await repo.save({}, table="notes")
    await repo.save({}, table="logs")
    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    assert mirror.tables() == ["logs", "notes"]
    mirror.close()


async def test_distinct_tags_returns_sorted(repo):
    await repo.save({}, table="notes", tags=["b"])
    await repo.save({}, table="notes", tags=["a", "c"])
    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    tags = mirror.distinct_tags()
    assert "a" in tags and "b" in tags and "c" in tags
    assert tags == sorted(tags)
    mirror.close()


async def test_arbitrary_sql_join(repo):
    await repo.save({"x": 1}, table="notes", tags=["important"])
    await repo.save({"x": 2}, table="notes", tags=["important"])
    await repo.save({"x": 3}, table="logs", tags=["chatter"])
    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    rows = mirror.fetchall(
        "SELECT r.ref FROM records r "
        "JOIN record_tags t ON t.ref = r.ref "
        "WHERE t.tag = ? AND r.table_name = ?",
        ("important", "notes"),
    )
    assert len(rows) == 2
    mirror.close()


async def test_execute_returns_cursor(repo):
    await repo.save({"x": 1}, table="notes")
    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    cur = mirror.execute("SELECT COUNT(*) FROM records")
    assert cur.fetchone()[0] == 1
    mirror.close()


async def test_iter_yields_all_records(repo):
    await repo.save({}, table="t1")
    await repo.save({}, table="t2")
    mirror = SqlMirror.open_memory()
    await mirror.sync(repo)
    rows = list(mirror)
    assert len(rows) == 2
    assert all("ref" in r for r in rows)
    mirror.close()


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


async def test_file_backed_mirror_survives_close_and_reopen(tmp_path: Path, repo):
    await repo.save({"x": 1}, table="notes", tags=["t"])

    db = tmp_path / "mirror.db"
    m1 = SqlMirror.open(db)
    await m1.sync(repo)
    m1.close()

    m2 = SqlMirror.open(db)
    assert m2.count_records() == 1
    assert "t" in m2.distinct_tags()
    m2.close()
