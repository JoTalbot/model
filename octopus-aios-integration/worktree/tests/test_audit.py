"""Tests for swarm.memory.audit -- append-only audit log + middleware."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.memory.audit import AuditedMemoryPort, AuditLog, _scheme_of
from swarm.memory.port import MemoryMetrics
from swarm.memory.types import (
    Artifact,
    Capabilities,
    RefMeta,
    RefNotFoundError,
)

# ---------------------------------------------------------------------------
# Tiny fake MemoryPort used to drive the middleware
# ---------------------------------------------------------------------------


class FakePort:
    def __init__(self) -> None:
        self._store: dict[str, Artifact] = {}
        self._metrics = MemoryMetrics()
        self._caps = Capabilities(
            schemes=frozenset({"file"}),
            supports_search=True,
            supports_delete=True,
            supports_promote=False,
        )
        self.fail_next_put = False
        self.fail_next_get = False

    @property
    def metrics(self) -> MemoryMetrics:
        return self._metrics

    def capabilities(self) -> Capabilities:
        return self._caps

    async def put(self, artifact: Artifact) -> str:
        if self.fail_next_put:
            self.fail_next_put = False
            raise RuntimeError("synthetic put failure")
        ref = f"ref:file:{len(self._store)}"
        self._store[ref] = artifact
        return ref

    async def get(self, ref: str) -> Artifact:
        if self.fail_next_get:
            self.fail_next_get = False
            raise RefNotFoundError(ref)
        if ref not in self._store:
            raise RefNotFoundError(ref)
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


# ---------------------------------------------------------------------------
# AuditLog -- write / iterate / rotate / stats
# ---------------------------------------------------------------------------


def test_audit_log_append_writes_one_jsonl_line(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    log.append({"op": "put", "ref": "ref:file:1", "ok": True, "bytes": 12})
    line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    payload = json.loads(line.strip())
    assert payload["op"] == "put"
    assert payload["ref"] == "ref:file:1"
    assert "ts" in payload


def test_audit_log_auto_stamps_ts(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    log.append({"op": "get", "ref": "x"})
    events = list(log.iter_events())
    assert events[0]["ts"]


def test_audit_log_rotates_daily(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=True)
    log.append({"ts": "2026-01-15T10:00:00+00:00", "op": "put"})
    log.append({"ts": "2026-01-16T10:00:00+00:00", "op": "put"})
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["audit-2026-01-15.jsonl", "audit-2026-01-16.jsonl"]


def test_audit_log_iter_filters_by_op(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    log.append({"op": "put", "ref": "r1"})
    log.append({"op": "get", "ref": "r1"})
    log.append({"op": "put", "ref": "r2"})
    puts = list(log.iter_events(op="put"))
    gets = list(log.iter_events(op="get"))
    assert len(puts) == 2
    assert len(gets) == 1


def test_audit_log_iter_filters_by_ref_and_scheme(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    log.append({"op": "put", "ref": "ref:catbox:url1", "scheme": "catbox"})
    log.append({"op": "put", "ref": "ref:nullpointer:url2", "scheme": "nullpointer"})
    catbox = list(log.iter_events(scheme="catbox"))
    assert len(catbox) == 1
    assert catbox[0]["ref"] == "ref:catbox:url1"


def test_audit_log_iter_filters_by_ok(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    log.append({"op": "put", "ok": True})
    log.append({"op": "put", "ok": False})
    log.append({"op": "put", "ok": True})
    ok_only = list(log.iter_events(ok=True))
    err_only = list(log.iter_events(ok=False))
    assert len(ok_only) == 2
    assert len(err_only) == 1


def test_audit_log_iter_filters_by_time_range(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    log.append({"ts": "2026-01-01T00:00:00+00:00", "op": "put"})
    log.append({"ts": "2026-06-01T00:00:00+00:00", "op": "put"})
    log.append({"ts": "2026-12-01T00:00:00+00:00", "op": "put"})
    summer = list(log.iter_events(
        since="2026-05-01T00:00:00+00:00",
        until="2026-09-01T00:00:00+00:00",
    ))
    assert len(summer) == 1


def test_audit_log_skips_malformed_lines(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    (tmp_path / "audit.jsonl").write_text(
        '{"op":"put"}\n'
        'garbage that is not json\n'
        '{"op":"get"}\n',
        encoding="utf-8",
    )
    events = list(log.iter_events())
    assert len(events) == 2
    assert {e["op"] for e in events} == {"put", "get"}


def test_audit_log_stats_aggregates(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    log.append({"op": "put", "ok": True, "bytes": 100, "scheme": "catbox"})
    log.append({"op": "put", "ok": True, "bytes": 200, "scheme": "catbox"})
    log.append({"op": "get", "ok": False, "bytes": 0, "scheme": "catbox"})
    log.append({"op": "get", "ok": True, "bytes": 50, "scheme": "nullpointer"})
    s = log.stats()
    assert s["total"] == 4
    assert s["per_op"] == {"put": 2, "get": 2}
    assert s["per_scheme_ok"]["catbox"] == 2
    assert s["per_scheme_err"]["catbox"] == 1
    assert s["per_scheme_ok"]["nullpointer"] == 1
    assert s["bytes_total"] == 350


def test_audit_log_empty_root_returns_empty_iter(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "does-not-exist", rotate_daily=False)
    assert list(log.iter_events()) == []
    assert log.stats()["total"] == 0


# ---------------------------------------------------------------------------
# scheme_of helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref, scheme",
    [
        ("ref:catbox:https://catbox.moe/x", "catbox"),
        ("ref:file:0", "file"),
        ("notaref", None),
        ("", None),
        (None, None),
    ],
)
def test_scheme_of_extracts(ref, scheme) -> None:
    assert _scheme_of(ref) == scheme


# ---------------------------------------------------------------------------
# AuditedMemoryPort -- middleware
# ---------------------------------------------------------------------------


async def test_audited_put_journals_on_success(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    port = AuditedMemoryPort(FakePort(), log, agent_id="agent-A")
    ref = await port.put(Artifact(content=b"hello"))
    events = list(log.iter_events())
    assert len(events) == 1
    ev = events[0]
    assert ev["op"] == "put"
    assert ev["ref"] == ref
    assert ev["ok"] is True
    assert ev["agent_id"] == "agent-A"
    assert ev["bytes"] == 5
    assert ev["latency_ms"] >= 0
    assert ev["scheme"] == "file"


async def test_audited_put_journals_on_failure(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    inner = FakePort()
    inner.fail_next_put = True
    port = AuditedMemoryPort(inner, log)
    with pytest.raises(RuntimeError, match="synthetic"):
        await port.put(Artifact(content=b"hi"))
    events = list(log.iter_events())
    assert len(events) == 1
    assert events[0]["ok"] is False
    assert "synthetic" in events[0]["error"]


async def test_audited_get_journals_size(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    inner = FakePort()
    port = AuditedMemoryPort(inner, log)
    ref = await port.put(Artifact(content=b"abcdefghij"))  # 10 bytes
    got = await port.get(ref)
    assert got.content == b"abcdefghij"
    get_events = list(log.iter_events(op="get"))
    assert len(get_events) == 1
    assert get_events[0]["bytes"] == 10
    assert get_events[0]["ok"] is True


async def test_audited_get_journals_not_found_error(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    port = AuditedMemoryPort(FakePort(), log)
    with pytest.raises(RefNotFoundError):
        await port.get("ref:file:does-not-exist")
    events = list(log.iter_events(op="get"))
    assert events[0]["ok"] is False
    assert "RefNotFoundError" in events[0]["error"]


async def test_audited_search_journals_result_count(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    inner = FakePort()
    port = AuditedMemoryPort(inner, log)
    await port.put(Artifact(content=b"a", tags=["x"]))
    await port.put(Artifact(content=b"b", tags=["x"]))
    results = await port.search(["x"])
    assert len(results) == 2
    search_events = list(log.iter_events(op="search"))
    assert len(search_events) == 1
    assert search_events[0]["meta"]["count"] == 2


async def test_audited_delete_journals_result(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    inner = FakePort()
    port = AuditedMemoryPort(inner, log)
    ref = await port.put(Artifact(content=b"x"))
    assert await port.delete(ref) is True
    assert await port.delete(ref) is False
    deletes = list(log.iter_events(op="delete"))
    assert len(deletes) == 2
    assert deletes[0]["meta"]["result"] is True
    assert deletes[1]["meta"]["result"] is False


async def test_audited_propagates_metrics_and_capabilities(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    inner = FakePort()
    port = AuditedMemoryPort(inner, log)
    assert port.metrics is inner.metrics
    assert port.capabilities() == inner.capabilities()


async def test_audited_log_failure_does_not_break_op(tmp_path: Path) -> None:
    class BrokenLog:
        def append(self, ev):
            raise OSError("disk full")

    port = AuditedMemoryPort(FakePort(), BrokenLog())  # type: ignore[arg-type]
    ref = await port.put(Artifact(content=b"x"))
    assert ref.startswith("ref:file:")


async def test_audited_supports_e2e_workflow(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, rotate_daily=False)
    port = AuditedMemoryPort(FakePort(), log, agent_id="node-1")
    ref = await port.put(Artifact(content=b"payload", tags=["t"]))
    assert await port.exists(ref) is True
    art = await port.get(ref)
    assert art.content == b"payload"
    deleted = await port.delete(ref)
    assert deleted is True
    s = log.stats()
    assert s["per_op"] == {"put": 1, "get": 1, "exists": 1, "delete": 1}
    assert s["per_scheme_ok"].get("file", 0) == 4
