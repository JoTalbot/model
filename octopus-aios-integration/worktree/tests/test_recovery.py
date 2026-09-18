"""Disaster-recovery tests: replicator, snapshot, bootstrap manifest."""

from __future__ import annotations

import json

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.recovery import (
    BootstrapManifest,
    ReplicationOutcome,
    Replicator,
    SwarmSnapshot,
    restore_repository,
    snapshot_repository,
)
from swarm.memory.repository import MemoryRepository
from swarm.memory.types import Artifact, Capabilities


class _FakeAdapter:
    """Minimal adapter that records every put() under a chosen scheme."""

    def __init__(self, scheme: str, *, raises: bool = False) -> None:
        self.scheme = scheme
        self.raises = raises
        self.last: Artifact | None = None

    async def put(self, artifact):
        if self.raises:
            raise RuntimeError(f"{self.scheme} down")
        self.last = artifact
        return f"ref:{self.scheme}:fake"

    async def get(self, ref):
        return self.last

    async def exists(self, ref):
        return self.last is not None

    async def delete(self, ref):
        self.last = None
        return True

    async def search(self, tags, owner):
        return []

    def capabilities(self):
        return Capabilities(
            schemes=frozenset({self.scheme}),
            supports_search=False,
            supports_delete=True,
            supports_promote=False,
        )


# ---------------------------------------------------------------------------
# Replicator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replicator_fans_to_every_target(tmp_path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "nullpointer": _FakeAdapter("nullpointer"),
            "catbox": _FakeAdapter("catbox"),
            "telegraph": _FakeAdapter("telegraph"),
        }
    )
    rep = Replicator(port)
    art = Artifact(content=b"critical", tags=["dr"])
    outcomes = await rep.replicate(
        art, schemes=["nullpointer", "catbox", "telegraph"]
    )
    assert len(outcomes) == 3
    assert all(o.ok for o in outcomes)
    refs = {o.ref for o in outcomes}
    assert refs == {"ref:nullpointer:fake", "ref:catbox:fake", "ref:telegraph:fake"}


@pytest.mark.asyncio
async def test_replicator_reports_partial_failure(tmp_path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "nullpointer": _FakeAdapter("nullpointer"),
            "telegraph": _FakeAdapter("telegraph", raises=True),
        }
    )
    rep = Replicator(port)
    outcomes = await rep.replicate(Artifact(content=b"x"))
    by_scheme = {o.scheme: o for o in outcomes}
    assert by_scheme["nullpointer"].ok
    assert not by_scheme["telegraph"].ok
    assert "telegraph down" in (by_scheme["telegraph"].error or "")


@pytest.mark.asyncio
async def test_replicator_default_schemes_skip_file(tmp_path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "nullpointer": _FakeAdapter("nullpointer"),
        }
    )
    outcomes = await Replicator(port).replicate(Artifact(content=b"x"))
    assert {o.scheme for o in outcomes} == {"nullpointer"}


@pytest.mark.asyncio
async def test_replicator_unknown_scheme_reports_error(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    outcomes = await Replicator(port).replicate(Artifact(content=b"x"), schemes=["ghost"])
    assert outcomes[0].scheme == "ghost"
    assert "ghost" in (outcomes[0].error or "")


# ---------------------------------------------------------------------------
# SwarmSnapshot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_dump_and_restore_round_trip(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "a")})
    await port.put(Artifact(content=b"alpha", tags=["v1"], attrs={"k": "v"}))
    await port.put(Artifact(content="второй", tags=["v2"]))

    bundle = await SwarmSnapshot(port).dump()
    lines = [ln for ln in bundle.splitlines() if ln]
    header = json.loads(lines[0])
    assert header["__gemaxi_snapshot__"] is True
    assert len(lines) == 3  # header + 2 records

    port_b = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "b")})
    new_refs = await SwarmSnapshot(port_b).restore(bundle)
    assert len(new_refs) == 2

    metas = await port_b.search([], owner=None)
    contents: list[bytes] = []
    for meta in metas:
        art = await port_b.get(meta.ref)
        body = art.content if isinstance(art.content, bytes) else art.content.encode("utf-8")
        contents.append(body)
    contents.sort()
    assert b"alpha" in contents and "второй".encode() in contents


@pytest.mark.asyncio
async def test_snapshot_restore_target_scheme_overrides_store_attr(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "src")})
    await port.put(Artifact(content=b"x"))
    bundle = await SwarmSnapshot(port).dump()

    captured = []

    class _Spy(_FakeAdapter):
        async def put(self, artifact):
            captured.append(artifact)
            return await super().put(artifact)

    port_b = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path / "dst"),
            "nullpointer": _Spy("nullpointer"),
        }
    )
    refs = await SwarmSnapshot(port_b).restore(bundle, target_scheme="nullpointer")
    assert refs == ["ref:nullpointer:fake"]
    assert captured[0].attrs.get("store") == "nullpointer"


@pytest.mark.asyncio
async def test_snapshot_restore_rejects_non_snapshot_payload(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    with pytest.raises(ValueError):
        await SwarmSnapshot(port).restore('{"not": "a snapshot"}\n')


@pytest.mark.asyncio
async def test_snapshot_dump_to_path_then_restore_from_path(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "src")})
    await port.put(Artifact(content=b"persist"))
    p = await SwarmSnapshot(port).dump_to_path(tmp_path / "dump.jsonl")
    assert p.is_file()

    port_b = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "dst")})
    refs = await SwarmSnapshot(port_b).restore_from_path(p)
    assert len(refs) == 1


# ---------------------------------------------------------------------------
# Repository snapshot helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repository_snapshot_round_trip(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "a")})
    repo = MemoryRepository(port)
    await repo.save({"v": 1}, table="parts", tags=["windshield"])
    await repo.save({"v": 2}, table="parts")
    bundle = await snapshot_repository(repo)
    assert '"kind": "repository"' in bundle

    port_b = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "b")})
    repo_b = MemoryRepository(port_b)
    refs = await restore_repository(repo_b, bundle)
    assert len(refs) == 2
    assert await repo_b.count(table="parts") == 2


@pytest.mark.asyncio
async def test_repository_restore_rejects_artifact_snapshot(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    artifact_bundle = await SwarmSnapshot(port).dump()
    repo = MemoryRepository(port)
    with pytest.raises(ValueError):
        await restore_repository(repo, artifact_bundle)


# ---------------------------------------------------------------------------
# BootstrapManifest
# ---------------------------------------------------------------------------

def test_manifest_round_trip_via_json():
    m = BootstrapManifest(notes="prod swarm")
    m.add_seed("10.0.0.1", 8000)
    m.add_seed("2.tcp.eu.ngrok.io", 12345, kind="ngrok")
    m.add_entry("ref:nullpointer:https://0x0.st/Ab", purpose="manifest_mirror")
    m.add_entry("ref:telegraph:Gemaxi-12-31", purpose="manifest_mirror")
    raw = m.to_json()
    parsed = BootstrapManifest.from_json(raw)
    assert parsed.notes == "prod swarm"
    assert len(parsed.seeds) == 2
    assert parsed.entries[0].scheme == "nullpointer"


def test_manifest_rejects_non_manifest_json():
    with pytest.raises(ValueError):
        BootstrapManifest.from_json('{"oops": true}')


def test_manifest_add_replication_filters_failures():
    m = BootstrapManifest()
    m.add_replication(
        [
            ReplicationOutcome(scheme="nullpointer", ref="ref:nullpointer:x"),
            ReplicationOutcome(scheme="ixio", error="500"),
        ],
        purpose="backup",
    )
    assert len(m.entries) == 1
    assert m.entries[0].ref == "ref:nullpointer:x"


def test_manifest_save_and_load_via_disk(tmp_path):
    m = BootstrapManifest(notes="phone-only seed")
    m.add_seed("127.0.0.1", 8000)
    p = m.save(tmp_path / "manifest.json")
    assert p.is_file()
    m2 = BootstrapManifest.load(p)
    assert m2.notes == "phone-only seed"
    assert m2.seeds[0]["port"] == 8000


@pytest.mark.asyncio
async def test_manifest_publish_and_fetch_round_trip(tmp_path):
    port = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "nullpointer": _FakeAdapter("nullpointer"),
        }
    )
    m = BootstrapManifest(notes="cold start")
    m.add_seed("a", 1)
    m.add_entry("ref:obsidian:home", purpose="primary")
    outcomes = await m.publish(Replicator(port), schemes=["nullpointer"])
    assert outcomes and outcomes[0].ok

    fetched = await BootstrapManifest.fetch(port, outcomes[0].ref)
    assert fetched.notes == "cold start"
    assert fetched.seeds[0]["host"] == "a"
