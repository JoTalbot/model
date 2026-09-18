"""Tests for the universal FileDropbox file-sharing layer."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.dropbox import (
    DEFAULT_CHUNK_SIZE,
    DropboxManifest,
    FileDropbox,
    download_file,
    upload_file,
)
from swarm.memory.types import Artifact, Capabilities, MemoryAdapterError

# ---------------------------------------------------------------------------
# Fake cloud adapter (in-memory) — lets us simulate N independent backends.
# ---------------------------------------------------------------------------

class _FakeCloud:
    """In-memory store that behaves like one anonymous pastebin."""

    def __init__(self, scheme: str) -> None:
        self.scheme = scheme
        self.store: dict[str, Artifact] = {}
        self._counter = 0

    async def put(self, artifact: Artifact) -> str:
        self._counter += 1
        key = f"ref:{self.scheme}:{self._counter:06d}"
        self.store[key] = Artifact(
            content=artifact.content
            if isinstance(artifact.content, bytes)
            else artifact.content.encode("utf-8"),
            mime=artifact.mime,
            tags=list(artifact.tags or []),
            provenance=dict(artifact.provenance or {}),
            attrs=dict(artifact.attrs or {}),
        )
        return key

    async def get(self, ref: str) -> Artifact:
        if ref not in self.store:
            from swarm.memory.types import RefNotFoundError

            raise RefNotFoundError(ref)
        return self.store[ref]

    async def exists(self, ref: str) -> bool:
        return ref in self.store

    async def delete(self, ref: str) -> bool:
        return self.store.pop(ref, None) is not None

    async def search(self, tags, owner):
        return []

    def capabilities(self) -> Capabilities:
        return Capabilities(
            schemes=frozenset({self.scheme}),
            supports_search=False,
            supports_delete=True,
            supports_promote=False,
        )


def _make_port(tmp_path: Path, *cloud_schemes: str) -> tuple[CompositeMemoryPort, dict[str, _FakeCloud]]:
    clouds = {s: _FakeCloud(s) for s in cloud_schemes}
    adapters: dict[str, object] = {"file": LocalScratchAdapter(tmp_path)}
    adapters.update(clouds)
    return CompositeMemoryPort(adapters), clouds


# ---------------------------------------------------------------------------
# Manifest serialisation
# ---------------------------------------------------------------------------

def test_manifest_roundtrip():
    m = DropboxManifest(
        name="x.bin",
        mime="application/octet-stream",
        size=10,
        sha256="abc",
        chunk_size=4,
        chunks=[],
    )
    raw = m.to_json()
    m2 = DropboxManifest.from_json(raw)
    assert m2.name == "x.bin" and m2.size == 10


def test_manifest_rejects_alien_json():
    with pytest.raises(ValueError):
        DropboxManifest.from_json('{"oops": true}')


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dropbox_round_trip_small_file(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "alpha", "beta", "gamma")
    payload = b"Hello, swarm!" * 100  # ~1.3 KB, single chunk
    src = tmp_path / "hello.txt"
    src.write_bytes(payload)

    drop = FileDropbox(port, replication=2)
    report = await drop.upload(src)
    assert report.manifest.sha256 == hashlib.sha256(payload).hexdigest()
    assert report.min_chunk_replicas == 2
    assert report.manifest_replicas >= 1

    out = tmp_path / "restored.txt"
    await drop.download(report.manifest_ref, out)
    assert out.read_bytes() == payload


@pytest.mark.asyncio
async def test_dropbox_round_trip_multi_chunk(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "a", "b", "c", "d")
    # 5 chunks of 1024 + tail
    payload = os.urandom(5 * 1024 + 137)
    src = tmp_path / "blob.bin"
    src.write_bytes(payload)

    drop = FileDropbox(port, chunk_size=1024, replication=3)
    report = await drop.upload(src)
    assert len(report.manifest.chunks) == 6
    assert all(r >= 3 for r in report.chunk_replicas)

    out = tmp_path / "got.bin"
    await drop.download(report.manifest_ref, out)
    assert out.read_bytes() == payload


@pytest.mark.asyncio
async def test_dropbox_round_trip_inmemory_bytes(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "a", "b")
    drop = FileDropbox(port, chunk_size=8, replication=2)
    report = await drop.upload(b"abcdefghijklmnop", name="anon.bin")
    out = tmp_path / "ret.bin"
    await drop.download(report.manifest_ref, out)
    assert out.read_bytes() == b"abcdefghijklmnop"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dropbox_survives_loss_of_one_replica(tmp_path: Path):
    port, clouds = _make_port(tmp_path / "scratch", "alpha", "beta", "gamma")
    payload = b"survive me" * 200
    drop = FileDropbox(port, replication=3, chunk_size=64)
    report = await drop.upload(payload, name="x.bin")
    assert report.manifest_replicas >= 2

    # Wipe one cloud entirely - including any manifest mirror that lived there.
    clouds["alpha"].store.clear()

    # Caller keeps every manifest mirror; download tolerates a dead one.
    out = tmp_path / "recover.bin"
    await drop.download(report.manifest_refs, out)
    assert out.read_bytes() == payload


@pytest.mark.asyncio
async def test_dropbox_fails_when_all_replicas_lost(tmp_path: Path):
    port, clouds = _make_port(tmp_path / "scratch", "alpha", "beta")
    drop = FileDropbox(port, replication=2, chunk_size=32)
    report = await drop.upload(b"x" * 100, name="x.bin")
    # Wipe both clouds, manifest included.
    for c in clouds.values():
        c.store.clear()
    with pytest.raises(MemoryAdapterError):
        await drop.download(report.manifest_ref, tmp_path / "no.bin")


@pytest.mark.asyncio
async def test_dropbox_no_upload_targets_raises(tmp_path: Path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    drop = FileDropbox(port)
    with pytest.raises(MemoryAdapterError):
        await drop.upload(b"x", name="x.bin")


@pytest.mark.asyncio
async def test_dropbox_detects_chunk_corruption(tmp_path: Path):
    port, clouds = _make_port(tmp_path / "scratch", "alpha")
    drop = FileDropbox(port, chunk_size=16, replication=1)
    report = await drop.upload(b"clean" * 20, name="x.bin")
    # Pick one chunk's ref and rewrite its bytes to garbage.
    chunk = report.manifest.chunks[0]
    bad_ref = chunk.refs[0]
    clouds["alpha"].store[bad_ref] = Artifact(content=b"GARBAGE", mime="application/octet-stream")

    with pytest.raises(MemoryAdapterError):
        await drop.download(report.manifest_ref, tmp_path / "broken.bin")


# ---------------------------------------------------------------------------
# Info / health / dropbox: prefix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dropbox_info_shows_replicas(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "a", "b", "c")
    drop = FileDropbox(port, chunk_size=8, replication=2)
    report = await drop.upload(b"info-me" * 4, name="info.bin")
    info = await drop.info(report.manifest_ref)
    assert info["name"] == "info.bin"
    assert info["min_replicas"] == 2
    assert all(c["replicas"] == 2 for c in info["chunks"])


@pytest.mark.asyncio
async def test_dropbox_health_after_partial_loss(tmp_path: Path):
    port, clouds = _make_port(tmp_path / "scratch", "alpha", "beta")
    drop = FileDropbox(port, replication=2, chunk_size=32)
    report = await drop.upload(b"x" * 80, name="h.bin")
    clouds["alpha"].store.clear()
    h = await drop.health(report.manifest_refs)
    assert h["recoverable"] is True
    assert all(len(c["alive"]) >= 1 for c in h["chunks"])


def test_dropbox_ref_helpers_idempotent():
    assert FileDropbox.dropbox_ref("ref:x:y") == "dropbox:ref:x:y"
    assert FileDropbox.dropbox_ref("dropbox:ref:x:y") == "dropbox:ref:x:y"


@pytest.mark.asyncio
async def test_dropbox_accepts_dropbox_prefixed_ref(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "a", "b")
    drop = FileDropbox(port, replication=2, chunk_size=16)
    report = await drop.upload(b"prefixed" * 10, name="p.bin")
    shorthand = FileDropbox.dropbox_ref(report.manifest_ref)
    out = tmp_path / "p.bin"
    await drop.download(shorthand, out)
    assert out.read_bytes() == b"prefixed" * 10


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_module_level_upload_download(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "a", "b")
    src = tmp_path / "in.bin"
    src.write_bytes(b"world" * 50)
    report = await upload_file(port, src)
    out = tmp_path / "out.bin"
    await download_file(port, report.manifest_ref, out)
    assert out.read_bytes() == b"world" * 50


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dropbox_progress_callback_fires(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "a", "b")
    drop = FileDropbox(port, chunk_size=8, replication=2)
    events: list[tuple[str, int, int]] = []
    await drop.upload(
        b"x" * 32, name="prog.bin", progress=lambda phase, d, t: events.append((phase, d, t))
    )
    phases = [e[0] for e in events]
    assert "chunk" in phases and "manifest" in phases


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_dropbox_rejects_bad_params(tmp_path: Path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    with pytest.raises(ValueError):
        FileDropbox(port, chunk_size=0)
    with pytest.raises(ValueError):
        FileDropbox(port, replication=0)


@pytest.mark.asyncio
async def test_dropbox_upload_missing_file_raises(tmp_path: Path):
    port, _ = _make_port(tmp_path / "scratch", "a")
    drop = FileDropbox(port, replication=1)
    with pytest.raises(FileNotFoundError):
        await drop.upload(tmp_path / "no-such-file.bin")


def test_default_chunk_size_fits_anonymous_pastebins():
    # Documented invariant: default chunk fits in 1 MB pastebins (dpaste).
    assert DEFAULT_CHUNK_SIZE < 1024 * 1024
