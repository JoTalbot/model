"""Tests for swarm.memory.zk_dropbox -- end-to-end zero-knowledge dropbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.dropbox import FileDropbox
from swarm.memory.types import Artifact, Capabilities, RefNotFoundError
from swarm.memory.zk_dropbox import (
    SUPPORTED_ALGOS,
    ZK_SCHEME,
    ZkDropbox,
    ZkShareLink,
    _b64u_decode,
    _b64u_encode,
)

# ---------------------------------------------------------------------------
# Fake cloud adapter -- copies pattern from tests/test_dropbox.py
# ---------------------------------------------------------------------------


class _FakeCloud:
    def __init__(self, scheme: str) -> None:
        self.scheme = scheme
        self.store: dict[str, Artifact] = {}
        self._n = 0

    async def put(self, artifact: Artifact) -> str:
        self._n += 1
        key = f"ref:{self.scheme}:{self._n:06d}"
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


def _make_dropbox(tmp_path: Path) -> tuple[FileDropbox, dict[str, _FakeCloud]]:
    clouds = {s: _FakeCloud(s) for s in ("alpha", "beta", "gamma")}
    adapters: dict[str, object] = {"file": LocalScratchAdapter(tmp_path)}
    adapters.update(clouds)
    port = CompositeMemoryPort(adapters)
    drop = FileDropbox(port, chunk_size=64, replication=2,
                       upload_schemes=list(clouds.keys()))
    return drop, clouds


# ---------------------------------------------------------------------------
# Link encoding
# ---------------------------------------------------------------------------


def test_b64u_round_trip():
    raw = bytes(range(32))
    assert _b64u_decode(_b64u_encode(raw)) == raw


def test_share_link_to_string_and_parse_round_trip():
    link = ZkShareLink(
        inner_ref="dropbox:ref:catbox:https://catbox.moe/x.json",
        key=b"\xab" * 32,
    )
    encoded = link.to_string()
    assert encoded.startswith(f"{ZK_SCHEME}:")
    assert "#key=" in encoded
    parsed = ZkShareLink.parse(encoded)
    assert parsed.inner_ref == link.inner_ref
    assert parsed.key == link.key
    assert parsed.algo in SUPPORTED_ALGOS


def test_share_link_parse_rejects_wrong_scheme():
    with pytest.raises(ValueError, match="not a zk"):
        ZkShareLink.parse("ref:catbox:x#key=zzz")


def test_share_link_parse_requires_fragment():
    with pytest.raises(ValueError, match="missing #key"):
        ZkShareLink.parse("zk:dropbox:ref:catbox:x")


def test_share_link_parse_requires_key_param():
    with pytest.raises(ValueError, match="missing key="):
        ZkShareLink.parse("zk:dropbox:ref:catbox:x#algo=aesgcm-v1")


def test_share_link_parse_rejects_unsupported_algo():
    with pytest.raises(ValueError, match="unsupported algo"):
        ZkShareLink.parse(
            f"zk:ref:x#key={_b64u_encode(b'k' * 32)}&algo=xor-v9"
        )


def test_share_link_parse_rejects_short_key():
    with pytest.raises(ValueError, match="32 bytes"):
        ZkShareLink.parse(f"zk:ref:x#key={_b64u_encode(b'short')}")


# ---------------------------------------------------------------------------
# Upload / download round-trip
# ---------------------------------------------------------------------------


async def test_zk_dropbox_round_trip_from_bytes(tmp_path: Path):
    drop, _ = _make_dropbox(tmp_path)
    zk = ZkDropbox(drop)

    plaintext = b"super secret payload " * 50
    share_link = await zk.upload(plaintext)

    assert share_link.startswith(f"{ZK_SCHEME}:")
    assert "#key=" in share_link

    out = tmp_path / "restored.bin"
    result_path = await zk.download(share_link, out)
    assert result_path == out
    assert out.read_bytes() == plaintext


async def test_zk_dropbox_round_trip_from_file(tmp_path: Path):
    drop, _ = _make_dropbox(tmp_path)
    zk = ZkDropbox(drop)

    src = tmp_path / "in.bin"
    plaintext = bytes(range(256)) * 4
    src.write_bytes(plaintext)

    share_link = await zk.upload(src)
    out = tmp_path / "restored.bin"
    await zk.download(share_link, out)
    assert out.read_bytes() == plaintext


async def test_zk_dropbox_ciphertext_is_unreadable_without_key(tmp_path: Path):
    drop, clouds = _make_dropbox(tmp_path)
    zk = ZkDropbox(drop)

    plaintext = b"watch this not appear on the paste " * 30
    await zk.upload(plaintext)  # результат не нужен: проверяем только шифрование

    # Inspect what landed in the simulated clouds: NO chunk should
    # contain the plaintext substring.
    needle = b"watch this not appear"
    for cloud in clouds.values():
        for blob in cloud.store.values():
            assert needle not in blob.content


async def test_zk_dropbox_wrong_key_rejects_decryption(tmp_path: Path):
    drop, _ = _make_dropbox(tmp_path)
    zk = ZkDropbox(drop)

    share_link = await zk.upload(b"hello world")
    inner_ref = share_link.split("#", 1)[0]
    forged = f"{inner_ref}#key={_b64u_encode(b'X' * 32)}&algo=aesgcm-v1"

    with pytest.raises(Exception):
        await zk.download(forged, tmp_path / "nope.bin")


async def test_zk_dropbox_supplied_key_used_verbatim(tmp_path: Path):
    drop, _ = _make_dropbox(tmp_path)
    zk = ZkDropbox(drop)

    my_key = b"\xff" * 32
    share_link = await zk.upload(b"deterministic", key=my_key)
    parsed = ZkShareLink.parse(share_link)
    assert parsed.key == my_key


async def test_zk_dropbox_rejects_bad_key_size(tmp_path: Path):
    drop, _ = _make_dropbox(tmp_path)
    zk = ZkDropbox(drop)
    with pytest.raises(ValueError, match="32 bytes"):
        await zk.upload(b"x", key=b"short")


async def test_zk_dropbox_info_includes_algo_and_key_size(tmp_path: Path):
    drop, _ = _make_dropbox(tmp_path)
    zk = ZkDropbox(drop)
    share_link = await zk.upload(b"hello")
    info = await zk.info(share_link)
    assert info["zk"]["algo"] == "aesgcm-v1"
    assert info["zk"]["key_bytes"] == 32
    assert "sha256" in info
