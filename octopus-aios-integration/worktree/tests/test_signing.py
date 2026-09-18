"""Ed25519 signing tests for the memory facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.signing import (
    SIG_ATTR,
    SignedMemoryPort,
    SigningKey,
    VerifyKey,
    is_signed,
    sign_artifact,
    signer_info,
    verify_artifact,
)
from swarm.memory.types import Artifact, MemoryAdapterError


def test_signing_key_generate_yields_valid_pair():
    k = SigningKey.generate()
    assert len(k.priv_bytes) == 32
    assert len(k.verify_key.pub_bytes) == 32
    assert len(k.key_id) == 16


def test_signing_key_b64_roundtrip():
    k = SigningKey.generate()
    k2 = SigningKey.from_b64(k.to_b64())
    assert k2.priv_bytes == k.priv_bytes
    assert k2.key_id == k.key_id


def test_verify_key_b64_roundtrip():
    k = SigningKey.generate()
    vk = VerifyKey.from_b64(k.verify_key.to_b64())
    assert vk.pub_bytes == k.verify_key.pub_bytes
    assert vk.key_id == k.verify_key.key_id


def test_verify_key_rejects_bad_length():
    with pytest.raises(ValueError):
        VerifyKey(pub_bytes=b"too-short")


def test_two_keys_have_distinct_key_ids():
    a = SigningKey.generate()
    b = SigningKey.generate()
    assert a.key_id != b.key_id


def test_sign_artifact_attaches_signature_block():
    k = SigningKey.generate()
    art = Artifact(content=b"hello", mime="text/plain", tags=["a"])
    signed = sign_artifact(art, k)
    assert is_signed(signed)
    info = signer_info(signed)
    assert info["alg"] == "ed25519" and info["key_id"] == k.key_id


def test_verify_artifact_round_trip():
    k = SigningKey.generate()
    art = Artifact(content=b"data", attrs={"author": "lisa"})
    signed = sign_artifact(art, k)
    ok, reason = verify_artifact(signed)
    assert ok and reason == "ok"


def test_verify_detects_content_tamper():
    k = SigningKey.generate()
    signed = sign_artifact(Artifact(content=b"clean"), k)
    tampered = Artifact(
        content=b"DIRTY",
        mime=signed.mime,
        tags=list(signed.tags),
        provenance=dict(signed.provenance),
        attrs=dict(signed.attrs),
    )
    ok, reason = verify_artifact(tampered)
    assert not ok and "signature" in reason


def test_verify_detects_attrs_tamper():
    k = SigningKey.generate()
    signed = sign_artifact(Artifact(content=b"x", attrs={"price": 100}), k)
    bad = Artifact(
        content=signed.content,
        mime=signed.mime,
        tags=list(signed.tags),
        provenance=dict(signed.provenance),
        attrs={**signed.attrs, "price": 999},
    )
    ok, _ = verify_artifact(bad)
    assert not ok


def test_verify_detects_keyid_pubkey_mismatch():
    k_a = SigningKey.generate()
    k_b = SigningKey.generate()
    signed = sign_artifact(Artifact(content=b"x"), k_a)
    block = dict(signed.attrs[SIG_ATTR])
    block["pubkey_b64"] = k_b.verify_key.to_b64()
    bad = Artifact(content=signed.content, attrs={**signed.attrs, SIG_ATTR: block})
    ok, reason = verify_artifact(bad)
    assert not ok and "key_id" in reason


def test_verify_with_trusted_ring_accepts_known_signer():
    k = SigningKey.generate()
    signed = sign_artifact(Artifact(content=b"x"), k)
    ok, _ = verify_artifact(signed, trusted={k.key_id: k.verify_key})
    assert ok


def test_verify_rejects_unknown_signer_when_required():
    k = SigningKey.generate()
    signed = sign_artifact(Artifact(content=b"x"), k)
    ok, reason = verify_artifact(signed, trusted={}, require_known_signer=True)
    assert not ok and "trusted ring" in reason


def test_verify_trusted_ring_mismatch_rejected():
    k = SigningKey.generate()
    k_other = SigningKey.generate()
    signed = sign_artifact(Artifact(content=b"x"), k)
    fake = VerifyKey(pub_bytes=k_other.verify_key.pub_bytes)
    ok, reason = verify_artifact(signed, trusted={k.key_id: fake})
    assert not ok and "mismatch" in reason


def test_verify_rejects_unsigned():
    ok, reason = verify_artifact(Artifact(content=b"x"))
    assert not ok and reason == "no signature"


def test_sign_is_deterministic_over_attrs_order():
    k = SigningKey.generate()
    a1 = Artifact(content=b"x", attrs={"a": 1, "b": 2}, tags=["x", "y"])
    a2 = Artifact(content=b"x", attrs={"b": 2, "a": 1}, tags=["y", "x"])
    s1 = sign_artifact(a1, k)
    s2 = sign_artifact(a2, k)
    assert s1.attrs[SIG_ATTR]["sig_b64"] == s2.attrs[SIG_ATTR]["sig_b64"]


@pytest.mark.asyncio
async def test_signed_port_put_get_round_trip(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    key = SigningKey.generate()
    port = SignedMemoryPort(inner, key)
    ref = await port.put(Artifact(content=b"signed body", tags=["k"]))
    art = await port.get(ref)
    assert art.content == b"signed body"
    assert is_signed(art)


@pytest.mark.asyncio
async def test_signed_port_rejects_unsigned_by_default(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    ref = await inner.put(Artifact(content=b"legacy"))
    port = SignedMemoryPort(inner, SigningKey.generate())
    with pytest.raises(MemoryAdapterError):
        await port.get(ref)


@pytest.mark.asyncio
async def test_signed_port_allow_unsigned_flag(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    ref = await inner.put(Artifact(content=b"legacy"))
    port = SignedMemoryPort(inner, SigningKey.generate(), allow_unsigned=True)
    art = await port.get(ref)
    assert art.content == b"legacy"


@pytest.mark.asyncio
async def test_signed_port_rejects_tampered_blob(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    key = SigningKey.generate()
    port = SignedMemoryPort(inner, key)
    ref = await port.put(Artifact(content=b"intact"))
    from swarm.memory.ref_parse import parse_ref

    _, opaque = parse_ref(ref)
    blob_path = tmp_path / opaque / "blob"
    blob_path.write_bytes(b"DIRTY!")
    with pytest.raises(MemoryAdapterError):
        await port.get(ref)


@pytest.mark.asyncio
async def test_signed_port_trusted_ring_strict(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    foreigner = SigningKey.generate()
    trustee = SigningKey.generate()
    untrusted_port = SignedMemoryPort(inner, foreigner)
    ref = await untrusted_port.put(Artifact(content=b"from foreigner"))
    reader = SignedMemoryPort(
        inner,
        trustee,
        trusted={trustee.key_id: trustee.verify_key},
        require_known_signer=True,
    )
    with pytest.raises(MemoryAdapterError):
        await reader.get(ref)


@pytest.mark.asyncio
async def test_signed_port_trust_and_untrust(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    sender = SigningKey.generate()
    sender_port = SignedMemoryPort(inner, sender)
    ref = await sender_port.put(Artifact(content=b"hi"))
    receiver = SignedMemoryPort(
        inner, SigningKey.generate(), require_known_signer=True
    )
    with pytest.raises(MemoryAdapterError):
        await receiver.get(ref)
    receiver.trust(sender.verify_key)
    assert sender.key_id in receiver.trusted_ids
    art = await receiver.get(ref)
    assert art.content == b"hi"
    assert receiver.untrust(sender.key_id) is True
    with pytest.raises(MemoryAdapterError):
        await receiver.get(ref)


@pytest.mark.asyncio
async def test_signed_port_metrics_proxied(tmp_path: Path):
    inner = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    port = SignedMemoryPort(inner, SigningKey.generate())
    await port.put(Artifact(content=b"x"))
    assert port.metrics.snapshot()["file"]["puts"] == 1
