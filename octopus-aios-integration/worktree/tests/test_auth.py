"""
tests/test_auth.py
──────────────────
Юнит-тесты для swarm/network/auth.py
"""
from __future__ import annotations

import time
import uuid

import pytest

from swarm.network.auth import (
    AuthSigner,
    AuthVerifier,
    NodeKeys,
    _canonical_body,
    make_auth_pair,
)

# ════════════════════════════════════════════════════════════════════════════
# Вспомогательные фикстуры
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def hmac_pair():
    signer   = AuthSigner(shared_secret="test-secret")
    verifier = AuthVerifier(shared_secret="test-secret")
    return signer, verifier


@pytest.fixture()
def open_pair():
    """Открытый режим — без secret и без Ed25519."""
    return AuthSigner(), AuthVerifier()


# ════════════════════════════════════════════════════════════════════════════
# canonical_body
# ════════════════════════════════════════════════════════════════════════════

def test_canonical_body_is_deterministic():
    env = {"method": "ping", "params": {"x": 1}, "auth": {"timestamp": 1.0, "nonce": "abc"}}
    assert _canonical_body(env) == _canonical_body(env)


def test_canonical_body_excludes_hmac_sig():
    env = {
        "method": "ping",
        "auth": {"timestamp": 1.0, "nonce": "n", "hmac": "aaa", "sig": "bbb"},
    }
    body = _canonical_body(env)
    assert b"hmac" not in body
    assert b"sig" not in body


# ════════════════════════════════════════════════════════════════════════════
# Открытый режим (auth-блок отсутствует)
# ════════════════════════════════════════════════════════════════════════════

def test_open_mode_no_auth_block(open_pair):
    signer, verifier = open_pair
    envelope = {"method": "ping", "params": {}}
    ok, reason = verifier.verify(envelope)
    assert ok, reason


# ════════════════════════════════════════════════════════════════════════════
# HMAC
# ════════════════════════════════════════════════════════════════════════════

def test_hmac_sign_verify(hmac_pair):
    signer, verifier = hmac_pair
    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    ok, reason = verifier.verify(envelope)
    assert ok, reason


def test_hmac_wrong_secret():
    signer   = AuthSigner(shared_secret="correct")
    verifier = AuthVerifier(shared_secret="wrong")
    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    ok, _ = verifier.verify(envelope)
    assert not ok


def test_hmac_tampered_payload(hmac_pair):
    signer, verifier = hmac_pair
    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    envelope["params"] = {"injected": True}   # подделка
    ok, _ = verifier.verify(envelope)
    assert not ok


# ════════════════════════════════════════════════════════════════════════════
# Антиреплей
# ════════════════════════════════════════════════════════════════════════════

def test_replay_rejected(hmac_pair):
    signer, verifier = hmac_pair
    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    ok1, _ = verifier.verify(envelope)
    ok2, reason = verifier.verify(envelope)   # повтор
    assert ok1
    assert not ok2
    assert "nonce" in reason or "replay" in reason


def test_clock_skew_rejected():
    verifier = AuthVerifier(shared_secret="s")
    signer   = AuthSigner(shared_secret="s")
    envelope = signer.sign_envelope({"method": "ping"})
    # Перемотаем timestamp в прошлое
    envelope["auth"]["timestamp"] = time.time() - 200
    ok, reason = verifier.verify(envelope)
    assert not ok
    assert "skew" in reason or "replay" in reason


# ════════════════════════════════════════════════════════════════════════════
# Ed25519 (пропускается если cryptography не установлен)
# ════════════════════════════════════════════════════════════════════════════

ed25519 = pytest.importorskip("cryptography", reason="cryptography not installed")


def test_ed25519_sign_verify(tmp_path):
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()

    signer   = AuthSigner(node_keys=keys)
    verifier = AuthVerifier(require_ed25519=True)

    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    ok, reason = verifier.verify(envelope)
    assert ok, reason


def test_ed25519_bad_signature(tmp_path):
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()

    signer   = AuthSigner(node_keys=keys)
    verifier = AuthVerifier(require_ed25519=True)

    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    # Испортим подпись
    envelope["auth"]["sig"] = "00" * 64
    ok, _ = verifier.verify(envelope)
    assert not ok


def test_ed25519_missing_sig(tmp_path):
    verifier = AuthVerifier(require_ed25519=True)
    envelope = {
        "method": "ping",
        "auth": {"timestamp": time.time(), "nonce": str(uuid.uuid4())},
    }
    ok, reason = verifier.verify(envelope)
    assert not ok
    assert "Ed25519" in reason


# ════════════════════════════════════════════════════════════════════════════
# make_auth_pair фабрика
# ════════════════════════════════════════════════════════════════════════════

def test_make_auth_pair_disabled():
    cfg = {"auth": {"enabled": False}}
    signer, verifier = make_auth_pair(cfg)
    # Должен работать без ошибок и пропускать всё
    envelope = signer.sign_envelope({"method": "hi"})
    ok, _ = verifier.verify(envelope)
    assert ok


def test_make_auth_pair_hmac(tmp_path):
    cfg = {
        "auth": {
            "enabled": True,
            "shared_secret": "supersecret",
            "require_ed25519": False,
            "generate_keys": False,
            "key_dir": str(tmp_path),
        }
    }
    signer, verifier = make_auth_pair(cfg)
    envelope = signer.sign_envelope({"method": "test"})
    ok, reason = verifier.verify(envelope)
    assert ok, reason


# ════════════════════════════════════════════════════════════════════════════
# PeerKeyRegistry в verify() — TODO #1 (итерация #23)
# ════════════════════════════════════════════════════════════════════════════

class FakePeerRegistry:
    """Простой mock PeerKeyRegistry для тестов."""

    def __init__(self):
        self._peers: dict[str, str] = {}

    def register(self, node_id: str, pubkey_hex: str, address: str = "") -> None:
        self._peers[node_id] = pubkey_hex

    def lookup_by_pubkey(self, pubkey_hex: str) -> str | None:
        pk = pubkey_hex.lower()
        for nid, pub in self._peers.items():
            if pub.lower() == pk:
                return nid
        return None


def test_ed25519_peer_registry_rejects_unknown(tmp_path):
    """Pubkey, не найденный в реестре → отклонение (не-handshake метод)."""
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()

    registry = FakePeerRegistry()
    # НЕ регистрируем ключи keys — они „чужие
# ════════════════════════════════════════════════════════════════════════════
# PeerKeyRegistry в verify() — TODO #1 (итерация #23)
# ════════════════════════════════════════════════════════════════════════════

class FakePeerRegistry:
    """Простой mock PeerKeyRegistry для тестов."""

    def __init__(self):
        self._peers = {}

    def register(self, node_id, pubkey_hex, address=""):
        self._peers[node_id] = pubkey_hex

    def lookup_by_pubkey(self, pubkey_hex):
        pk = pubkey_hex.lower()
        for nid, pub in self._peers.items():
            if pub.lower() == pk:
                return nid
        return None


def test_ed25519_peer_registry_rejects_unknown(tmp_path):
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()
    registry = FakePeerRegistry()
    signer   = AuthSigner(node_keys=keys)
    verifier = AuthVerifier(require_ed25519=True, peer_registry=registry)
    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    ok, reason = verifier.verify(envelope)
    assert not ok, "Ожидали отклонение - pubkey не в реестре"
    assert "реестр" in reason.lower() or "registry" in reason.lower()


def test_ed25519_peer_registry_allows_known(tmp_path):
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()
    registry = FakePeerRegistry()
    registry.register(keys.node_id, keys.public_key_hex())
    signer   = AuthSigner(node_keys=keys)
    verifier = AuthVerifier(require_ed25519=True, peer_registry=registry)
    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    ok, reason = verifier.verify(envelope)
    assert ok, reason


def test_ed25519_handshake_bypasses_registry(tmp_path):
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()
    registry = FakePeerRegistry()
    signer   = AuthSigner(node_keys=keys)
    verifier = AuthVerifier(require_ed25519=True, peer_registry=registry)
    for method in ["handshake_hello", "handshake_ack", "handshake_done", "handshake_request"]:
        envelope = signer.sign_envelope({"method": method, "params": {}})
        ok, reason = verifier.verify(envelope)
        assert ok, f"Handshake {method} должен проходить без проверки реестра: {reason}"


def test_register_peer_key_also_registers_in_registry(tmp_path):
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()
    registry = FakePeerRegistry()
    verifier = AuthVerifier(require_ed25519=True, peer_registry=registry)
    verifier.register_peer_key("test-node", keys.public_key_hex())
    found = registry.lookup_by_pubkey(keys.public_key_hex())
    assert found == "test-node"


def test_ed25519_no_registry_fallback(tmp_path):
    keys = NodeKeys(tmp_path)
    keys.load_or_generate()
    signer   = AuthSigner(node_keys=keys)
    verifier = AuthVerifier(require_ed25519=True)
    envelope = signer.sign_envelope({"method": "ping", "params": {}})
    ok, reason = verifier.verify(envelope)
    assert ok, reason


def test_make_auth_pair_with_registry(tmp_path):
    registry = FakePeerRegistry()
    cfg = {
        "auth": {
            "enabled": True,
            "shared_secret": "",
            "require_ed25519": True,
            "generate_keys": True,
            "key_dir": str(tmp_path),
        }
    }
    signer, verifier = make_auth_pair(cfg, peer_registry=registry)
    assert verifier._peer_registry is registry
