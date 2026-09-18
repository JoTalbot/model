"""
tests/test_handshake.py
────────────────────────
Юнит и интеграционные тесты HandshakeManager + PeerKeyRegistry.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from swarm.network.handshake import (
    HandshakeManager,
    PeerKeyRegistry,
    _check_timestamp,
    _sign_payload,
    _verify_payload,
)

# ── Пропуск если нет cryptography ────────────────────────────────────────────
crypto = pytest.importorskip("cryptography", reason="cryptography not installed")

from swarm.network.auth import NodeKeys

# ════════════════════════════════════════════════════════════════════════════
# Фикстуры
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def keys_a(tmp_path):
    k = NodeKeys(tmp_path / "a")
    k.load_or_generate()
    return k


@pytest.fixture()
def keys_b(tmp_path):
    k = NodeKeys(tmp_path / "b")
    k.load_or_generate()
    return k


@pytest.fixture()
def registry_a():
    return PeerKeyRegistry()


@pytest.fixture()
def registry_b():
    return PeerKeyRegistry()


@pytest.fixture()
def mgr_a(keys_a, registry_a):
    return HandshakeManager(keys_a, registry_a, require_ed25519=True)


@pytest.fixture()
def mgr_b(keys_b, registry_b):
    return HandshakeManager(keys_b, registry_b, require_ed25519=True)


# ════════════════════════════════════════════════════════════════════════════
# PeerKeyRegistry
# ════════════════════════════════════════════════════════════════════════════

def test_registry_register_get(registry_a, keys_b):
    registry_a.register("node-B", keys_b.public_key_hex(), "127.0.0.1:10002")
    assert "node-B" in registry_a
    assert registry_a.get("node-B").pubkey_hex == keys_b.public_key_hex()


def test_registry_unregister(registry_a, keys_b):
    registry_a.register("node-B", keys_b.public_key_hex())
    registry_a.unregister("node-B")
    assert "node-B" not in registry_a


def test_registry_all_peers(registry_a, keys_a, keys_b):
    registry_a.register("A", keys_a.public_key_hex())
    registry_a.register("B", keys_b.public_key_hex())
    assert len(registry_a.all_peers()) == 2


# ════════════════════════════════════════════════════════════════════════════
# Подпись/верификация payload
# ════════════════════════════════════════════════════════════════════════════

def test_sign_verify_ok(keys_a):
    payload = {"node_id": "A", "timestamp": time.time()}
    sig = _sign_payload(keys_a, payload)
    assert _verify_payload(keys_a.public_key_hex(), payload, sig)


def test_verify_wrong_pubkey(keys_a, keys_b):
    payload = {"node_id": "A", "timestamp": time.time()}
    sig = _sign_payload(keys_a, payload)
    # Верифицируем чужим ключом — должно вернуть False
    assert not _verify_payload(keys_b.public_key_hex(), payload, sig)


def test_verify_tampered_payload(keys_a):
    payload = {"node_id": "A", "timestamp": time.time()}
    sig = _sign_payload(keys_a, payload)
    payload["node_id"] = "HACKER"   # подмена
    assert not _verify_payload(keys_a.public_key_hex(), payload, sig)


# ════════════════════════════════════════════════════════════════════════════
# Timestamp check
# ════════════════════════════════════════════════════════════════════════════

def test_timestamp_fresh():
    assert _check_timestamp(time.time())


def test_timestamp_old():
    assert not _check_timestamp(time.time() - 100)


def test_timestamp_future():
    assert not _check_timestamp(time.time() + 100)


# ════════════════════════════════════════════════════════════════════════════
# Handshake: симуляция через прямые вызовы обработчиков
# (без реального TCP — тестируем логику)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_handshake_hello_ack_done(mgr_a, mgr_b, keys_a, keys_b):
    """Полный happy-path: A → hello → B → ack → A → done → B."""

    # A формирует hello
    ts = time.time()
    signed = {"node_id": keys_a.node_id, "pubkey": keys_a.public_key_hex(), "timestamp": ts, "address": ""}
    hello = {
        "node_id":   keys_a.node_id,
        "pubkey":    keys_a.public_key_hex(),
        "timestamp": ts,
        "address":   "",
        "sig":       _sign_payload(keys_a, signed),
    }

    # B получает hello
    ack = await mgr_b._handle_hello(hello)
    assert ack["ok"], f"ack не ok: {ack}"
    assert ack["node_id"] == keys_b.node_id

    # Регистрируем B у A
    mgr_a._registry.register(ack["node_id"], ack["pubkey"], "127.0.0.1:10002")

    # A отправляет done
    done_ts = time.time()
    done_signed = {"node_id": keys_a.node_id, "timestamp": done_ts}
    done = {
        "node_id":   keys_a.node_id,
        "timestamp": done_ts,
        "sig":       _sign_payload(keys_a, done_signed),
    }

    # Нужно сначала зарегистрировать A у B (через pending)
    mgr_b._registry.register(keys_a.node_id, keys_a.public_key_hex(), "")
    result = await mgr_b._handle_done(done)
    assert result["ok"], f"done не ok: {result}"


@pytest.mark.asyncio
async def test_handshake_hello_invalid_sig(mgr_b, keys_a):
    """Hello с неверной подписью должен быть отклонён."""
    ts = time.time()
    hello = {
        "node_id":   keys_a.node_id,
        "pubkey":    keys_a.public_key_hex(),
        "timestamp": ts,
        "sig":       "00" * 64,   # неверная подпись
    }
    result = await mgr_b._handle_hello(hello)
    assert not result["ok"]
    assert result["reason"] == "invalid_sig"


@pytest.mark.asyncio
async def test_handshake_hello_clock_skew(mgr_b, keys_a):
    """Hello со старым timestamp должен быть отклонён."""
    ts = time.time() - 200
    hello = {
        "node_id":   keys_a.node_id,
        "pubkey":    keys_a.public_key_hex(),
        "timestamp": ts,
        "sig":       "",
    }
    result = await mgr_b._handle_hello(hello)
    assert not result["ok"]
    assert result["reason"] == "clock_skew"


@pytest.mark.asyncio
async def test_handshake_done_without_hello(mgr_b, keys_a):
    """Done без предшествующего hello должен быть отклонён."""
    result = await mgr_b._handle_done({
        "node_id":   "ghost-node",
        "timestamp": time.time(),
        "sig":       "",
    })
    assert not result["ok"]
    assert result["reason"] == "no_hello"


# ════════════════════════════════════════════════════════════════════════════
# stats()
# ════════════════════════════════════════════════════════════════════════════

def test_handshake_stats(mgr_a):
    s = mgr_a.stats()
    assert "known_peers"    in s
    assert "pending_shakes" in s
    assert s["require_ed25519"] is True



def test_handshake_hello_address_registered(tmp_path):
    """Address из hello-payload попадает в PeerKeyRegistry."""
    import time

    from swarm.network.auth import NodeKeys
    from swarm.network.handshake import HandshakeManager, PeerKeyRegistry

    keys = NodeKeys(tmp_path)
    keys.load_or_generate()
    registry = PeerKeyRegistry()
    mgr = HandshakeManager(node_keys=keys, registry=registry, require_ed25519=False)

    async def run_test():
        hello_params = {
            "node_id": keys.node_id,
            "pubkey": keys.public_key_hex(),
            "timestamp": time.time(),
            "address": "192.168.1.100:8300",
        }
        result = await mgr._handle_hello(hello_params)
        assert result["ok"], f"Hello должен пройти: {result}"
        peer = registry.get(keys.node_id)
        assert peer is not None, "Пир должен быть в реестре"
        assert peer.address == "192.168.1.100:8300", f"Expected 192.168.1.100:8300, got {peer.address}"

    asyncio.run(run_test())  # fixed: get_event_loop() deprecated in Python 3.10+
