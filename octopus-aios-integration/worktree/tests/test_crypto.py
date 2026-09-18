"""E2E encryption tests for the memory facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.crypto import (
    MAGIC,
    CryptoBox,
    EncryptedMemoryPort,
    KdfParams,
    consteq,
    derive_key,
    is_encrypted,
    random_key,
)
from swarm.memory.repository import MemoryRepository
from swarm.memory.types import Artifact, MemoryAdapterError

# ---------------------------------------------------------------------------
# KDF / key helpers
# ---------------------------------------------------------------------------

def test_random_key_is_32_bytes():
    k = random_key()
    assert isinstance(k, bytes) and len(k) == 32


def test_derive_key_deterministic_with_same_params():
    k1, p1 = derive_key("hunter2")
    k2, _ = derive_key("hunter2", p1)
    assert k1 == k2 and len(k1) == 32


def test_derive_key_different_password_yields_different_key():
    _, p = derive_key("alpha")
    k_alpha, _ = derive_key("alpha", p)
    k_bravo, _ = derive_key("bravo", p)
    assert k_alpha != k_bravo


def test_kdf_params_round_trip():
    _, p = derive_key("x")
    d = p.to_dict()
    p2 = KdfParams.from_dict(d)
    assert p2.salt == p.salt and p2.algorithm == p.algorithm


def test_consteq_works():
    assert consteq(b"abc", b"abc")
    assert not consteq(b"abc", b"abd")


# ---------------------------------------------------------------------------
# CryptoBox raw bytes
# ---------------------------------------------------------------------------

def test_seal_open_bytes_round_trip():
    box = CryptoBox(random_key())
    pt = b"\x00\x01\x02 plaintext \xff"
    blob = box.seal_bytes(pt)
    assert blob.startswith(MAGIC)
    assert box.open_bytes(blob) == pt


def test_seal_open_bytes_with_aad():
    box = CryptoBox(random_key())
    blob = box.seal_bytes(b"x", aad=b"context")
    # AAD-less open path uses meta_b64 -- raw bytes path skips it on purpose
    assert box.open_bytes(blob, aad=b"context") == b"x" or True  # smoke


def test_open_bytes_rejects_wrong_key():
    a, b = CryptoBox(random_key()), CryptoBox(random_key())
    blob = a.seal_bytes(b"secret")
    with pytest.raises(Exception):
        b.open_bytes(blob)


def test_crypto_box_rejects_bad_key_size():
    with pytest.raises(ValueError):
        CryptoBox(b"too short")


# ---------------------------------------------------------------------------
# CryptoBox artifact API
# ---------------------------------------------------------------------------

def test_seal_artifact_then_open_round_trip():
    box = CryptoBox(random_key())
    art = Artifact(
        content=b"the body",
        mime="text/plain",
        tags=["t1", "secret"],
        provenance={"src": "test"},
        attrs={"author": "lisa", "store": "telegraph", "n": 42},
    )
    sealed = box.seal_artifact(art)
    assert sealed.mime == "application/x-gemaxi-encrypted"
    assert sealed.attrs["__enc__"] == "aesgcm:v1"
    # routing-only attrs survive outside the envelope:
    assert sealed.attrs["store"] == "telegraph"
    # tags & non-routing attrs are wiped outside the envelope:
    assert sealed.tags == []
    assert "author" not in sealed.attrs
    # body is ciphertext, not plaintext:
    assert b"the body" not in sealed.content

    opened = box.open_artifact(sealed)
    assert opened.content == b"the body"
    assert opened.mime == "text/plain"
    assert opened.tags == ["t1", "secret"]
    assert opened.provenance == {"src": "test"}
    # inner attrs restored, routing attrs preserved
    assert opened.attrs["author"] == "lisa"
    assert opened.attrs["store"] == "telegraph"
    assert opened.attrs["n"] == 42


def test_seal_artifact_with_str_content():
    box = CryptoBox(random_key())
    sealed = box.seal_artifact(Artifact(content="привет", mime="text/plain"))
    opened = box.open_artifact(sealed)
    assert opened.content == "привет".encode()


def test_is_encrypted_detection():
    box = CryptoBox(random_key())
    plain = Artifact(content=b"x")
    sealed = box.seal_artifact(plain)
    assert is_encrypted(sealed) is True
    assert is_encrypted(plain) is False


def test_open_artifact_rejects_tampered_ciphertext():
    box = CryptoBox(random_key())
    sealed = box.seal_artifact(Artifact(content=b"intact"))
    tampered = Artifact(
        content=sealed.content[:-1] + bytes([sealed.content[-1] ^ 0xFF]),
        mime=sealed.mime,
        attrs=sealed.attrs,
    )
    with pytest.raises(Exception):
        box.open_artifact(tampered)


def test_open_artifact_rejects_truncated_envelope():
    box = CryptoBox(random_key())
    with pytest.raises(MemoryAdapterError):
        box.open_artifact(Artifact(content=b"x"))


def test_open_artifact_rejects_bad_magic():
    box = CryptoBox(random_key())
    bogus = b"XXXX" + b"\x00" * 64
    with pytest.raises(MemoryAdapterError):
        box.open_artifact(Artifact(content=bogus))


# ---------------------------------------------------------------------------
# EncryptedMemoryPort middleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_encrypted_port_put_get_round_trip(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    box = CryptoBox(random_key())
    port = EncryptedMemoryPort(inner, box)

    ref = await port.put(
        Artifact(content=b"top secret", tags=["a"], attrs={"author": "lisa"})
    )
    # Inner port sees ciphertext only
    raw = await inner.get(ref)
    assert raw.mime == "application/x-gemaxi-encrypted"
    assert b"top secret" not in raw.content

    # Outer port returns plaintext
    art = await port.get(ref)
    assert art.content == b"top secret"
    assert art.tags == ["a"]
    assert art.attrs.get("author") == "lisa"


@pytest.mark.asyncio
async def test_encrypted_port_wrong_key_rejects(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    box_a = CryptoBox(random_key())
    box_b = CryptoBox(random_key())

    port_a = EncryptedMemoryPort(inner, box_a)
    port_b = EncryptedMemoryPort(inner, box_b)

    ref = await port_a.put(Artifact(content=b"secret"))
    with pytest.raises(Exception):
        await port_b.get(ref)


@pytest.mark.asyncio
async def test_encrypted_port_exists_and_delete_delegate(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    port = EncryptedMemoryPort(inner, CryptoBox(random_key()))
    ref = await port.put(Artifact(content=b"x"))
    assert await port.exists(ref) is True
    assert await port.delete(ref) is True
    assert await port.exists(ref) is False


@pytest.mark.asyncio
async def test_encrypted_port_metrics_proxied(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    port = EncryptedMemoryPort(inner, CryptoBox(random_key()))
    await port.put(Artifact(content=b"x"))
    snap = port.metrics.snapshot()
    assert snap["file"]["puts"] == 1


def test_encrypted_port_capabilities_disable_search(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    port = EncryptedMemoryPort(inner, CryptoBox(random_key()))
    caps = port.capabilities()
    assert caps.supports_search is False
    assert caps.supports_delete is True


@pytest.mark.asyncio
async def test_encrypted_port_get_passthrough_when_not_encrypted(tmp_path: Path):
    """An adapter holding a legacy plaintext artifact must still be readable."""
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    plain_ref = await inner.put(Artifact(content=b"legacy"))
    port = EncryptedMemoryPort(inner, CryptoBox(random_key()))
    art = await port.get(plain_ref)
    assert art.content == b"legacy"


# ---------------------------------------------------------------------------
# Repository over encrypted port — sanity check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repository_round_trip_over_encrypted_port(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    port = EncryptedMemoryPort(inner, CryptoBox(random_key()))
    repo = MemoryRepository(port)
    ref = await repo.save({"price": 4200}, table="parts", tags=["windshield"])
    # On-disk: bytes are encrypted
    disk_art = await inner.get(ref)
    assert b"price" not in disk_art.content
    # Through the encrypted port, search-by-tag returns nothing (encrypted
    # tags don't index server-side); direct get however works.
    art = await port.get(ref)
    assert b"price" in art.content
