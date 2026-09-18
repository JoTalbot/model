"""
swarm/network/auth.py
─────────────────────
Межнодовая авторизация на основе Ed25519 + HMAC-SHA256.

Схема работы
────────────
• Каждая нода при старте генерирует (или загружает) пару ключей Ed25519.
• RPC: клиент подписывает (method + params_hash + timestamp + nonce) своим
  приватным ключом. Сервер верифицирует подпись публичным ключом отправителя.
• Gossip: UDP-пакет содержит поле `sig` — Ed25519-подпись тела пакета.
• Опционально — простой HMAC-режим (shared_secret) для закрытых сетей.

Защита от replay-атак
──────────────────────
Timestamp должен быть в пределах ±MAX_CLOCK_SKEW_SEC от времени сервера.
Nonce хранится в LRU-кэше NONCE_TTL_SEC секунд.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Константы ──────────────────────────────────────────────────────────────
MAX_CLOCK_SKEW_SEC: int = 30   # допустимое расхождение часов
NONCE_TTL_SEC: int = 60        # как долго помним nonce
NONCE_CACHE_SIZE: int = 10_000 # максимум nonce в кэше

# ── Попытка импорта cryptography (Ed25519) ──────────────────────────────────
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )
    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTO = False
    logger.warning(
        "Пакет `cryptography` не установлен. "
        "Ed25519-подписи недоступны — работает только HMAC-режим. "
        "Установи: pip install cryptography"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Хранилище ключей
# ══════════════════════════════════════════════════════════════════════════════

class NodeKeys:
    """Пара ключей Ed25519 текущей ноды."""

    def __init__(self, key_dir: str | Path = ".swarm_keys") -> None:
        self._dir = Path(key_dir)
        self._private_key: Any = None   # Ed25519PrivateKey
        self._public_key: Any = None    # Ed25519PublicKey
        self.public_bytes: bytes = b""  # raw 32-byte pubkey
        self.node_id: str = ""          # hex(sha256(pubkey))[:16]

    # ── Загрузка / генерация ─────────────────────────────────────────────────

    def load_or_generate(self) -> None:
        """Загрузить ключи из файла или сгенерировать новые."""
        if not _HAS_CRYPTO:
            self._fallback_init()
            return

        self._dir.mkdir(parents=True, exist_ok=True)
        priv_path = self._dir / "node.key"
        pub_path  = self._dir / "node.pub"

        if priv_path.exists() and pub_path.exists():
            self._load(priv_path, pub_path)
            logger.info("Ключи ноды загружены из %s", self._dir)
        else:
            self._generate(priv_path, pub_path)
            logger.info("Новые ключи ноды сгенерированы в %s", self._dir)

    def _generate(self, priv_path: Path, pub_path: Path) -> None:
        key = Ed25519PrivateKey.generate()
        priv_bytes = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        pub_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

        priv_path.write_bytes(priv_bytes)
        priv_path.chmod(0o600)
        pub_path.write_bytes(pub_raw.hex().encode())

        self._private_key = key
        self._public_key  = key.public_key()
        self.public_bytes  = pub_raw
        self.node_id       = hashlib.sha256(pub_raw).hexdigest()[:16]

    def _load(self, priv_path: Path, pub_path: Path) -> None:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        priv_bytes = priv_path.read_bytes()
        self._private_key = load_pem_private_key(priv_bytes, password=None)
        self._public_key  = self._private_key.public_key()
        self.public_bytes  = self._public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.node_id       = hashlib.sha256(self.public_bytes).hexdigest()[:16]

    def _fallback_init(self) -> None:
        """Заглушка без cryptography — только для dev/test."""
        self.public_bytes = os.urandom(32)
        self.node_id = hashlib.sha256(self.public_bytes).hexdigest()[:16]
        logger.warning("NodeKeys работает в заглушечном режиме (без cryptography).")

    # ── Подпись / верификация ────────────────────────────────────────────────

    def sign(self, message: bytes) -> bytes:
        """Подписать bytes. Возвращает 64-байтовую подпись."""
        if not _HAS_CRYPTO or self._private_key is None:
            return b""
        return self._private_key.sign(message)

    def public_key_hex(self) -> str:
        return self.public_bytes.hex()


# ══════════════════════════════════════════════════════════════════════════════
# Верификатор (сервер)
# ══════════════════════════════════════════════════════════════════════════════

class AuthVerifier:
    """
    Верифицирует входящие RPC/Gossip-сообщения.

    Режимы:
      - Ed25519  (require_ed25519=True, нужен `cryptography`)
      - HMAC     (shared_secret задан)
      - Открытый (оба отключены — только для dev)
    """

    # ── Публичный реестр ─────────────────────────────────────────────────────

    def register_peer_key(self, node_id: str, pubkey_hex: str) -> None:
        """Зарегистрировать публичный ключ пира (при handshake)."""
        self._peer_keys[node_id] = bytes.fromhex(pubkey_hex)
        if self._peer_registry is not None:
            try:
                self._peer_registry.register(node_id, pubkey_hex)
            except Exception:
                pass  # non-fatal

    def __init__(
        self,
        *,
        shared_secret: str = "",
        require_ed25519: bool = False,
        peer_registry=None,  # PeerKeyRegistry | None
        own_pubkey: str = "",  # hex pubkey этой ноды (для self-signed запросов)
    ) -> None:
        self._secret = shared_secret.encode() if shared_secret else b""
        self._require_ed25519 = require_ed25519 and _HAS_CRYPTO
        self._nonces: OrderedDict[str, float] = OrderedDict()
        self._peer_keys: dict[str, bytes] = {}  # node_id → raw pubkey bytes
        self._peer_registry = peer_registry
        self._own_pubkey = own_pubkey.lower() if own_pubkey else None

    # ── Верификация HMAC ─────────────────────────────────────────────────────

    def verify_hmac(self, body: bytes, token: str) -> bool:
        if not self._secret:
            return True  # HMAC не настроен — пропускаем
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, token)

    # ── Верификация Ed25519 ───────────────────────────────────────────────────

    def verify_ed25519(
        self, body: bytes, signature_hex: str, pubkey_hex: str
    ) -> bool:
        if not _HAS_CRYPTO:
            return True
        try:
            pubkey = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
            pubkey.verify(bytes.fromhex(signature_hex), body)
            return True
        except (InvalidSignature, ValueError):
            return False

    # ── Антиреплей ───────────────────────────────────────────────────────────

    def check_replay(self, nonce: str, timestamp: float) -> bool:
        """True — сообщение свежее и nonce не видели."""
        now = time.time()
        if abs(now - timestamp) > MAX_CLOCK_SKEW_SEC:
            logger.warning("Отклонён пакет: clock skew %.1fs", now - timestamp)
            return False
        self._expire_nonces(now)
        if nonce in self._nonces:
            logger.warning("Отклонён пакет: повторный nonce %s", nonce)
            return False
        self._nonces[nonce] = now + NONCE_TTL_SEC
        if len(self._nonces) > NONCE_CACHE_SIZE:
            self._nonces.popitem(last=False)
        return True

    def _expire_nonces(self, now: float) -> None:
        expired = [k for k, exp in self._nonces.items() if exp < now]
        for k in expired:
            del self._nonces[k]

    # ── Единая точка верификации ─────────────────────────────────────────────

    def verify(self, envelope: dict) -> tuple[bool, str]:
        """
        Верифицировать конверт сообщения.

        Ожидаемые поля в envelope:
          auth.timestamp  — float (unix)
          auth.nonce      — str (uuid4)
          auth.hmac       — str (опционально)
          auth.sig        — str hex (опционально, Ed25519)
          auth.pubkey     — str hex (опционально, Ed25519)

        Возвращает (ok: bool, reason: str).
        """
        # ── Whitelist для handshake-методов ─────────────────────────────────
        # Парадокс «курица-яйцо»: handshake_hello/ack/done передают pubkey пира
        # ВПЕРВЫЕ. До hello мы ключа не знаем, поэтому строгую проверку
        # ed25519/HMAC пропускаем именно для этих 3 методов. Если auth-блок
        # всё-таки приложен (а signer добавляет его всегда), мы валидируем его
        # как обычно — это даёт целостность пакета без жёсткой аутентификации.
        _HANDSHAKE_METHODS = {
            "handshake_hello",
            "handshake_ack",
            "handshake_done",
            "handshake_request",  # admin-инициация handshake к новому пиру
            "recruit_fetch",      # child скачивает архив до регистрации в реестре
            "peer_list",           # child запрашивает список пиров у parent
            "peer_keys",           # child запрашивает публичные ключи пиров
        }
        method = envelope.get("method", "")
        is_handshake = method in _HANDSHAKE_METHODS

        auth = envelope.get("auth", {})
        if not auth:
            if is_handshake:
                return True, "ok-handshake-no-auth"
            if self._secret or self._require_ed25519:
                return False, "Отсутствует блок auth"
            return True, "ok"  # открытый режим

        ts    = auth.get("timestamp", 0.0)
        nonce = auth.get("nonce", "")

        if not self.check_replay(nonce, float(ts)):
            return False, "replay / clock skew"

        # HMAC
        if self._secret:
            body = _canonical_body(envelope)
            if not self.verify_hmac(body, auth.get("hmac", "")):
                return False, "Неверный HMAC"

        # Ed25519
        if self._require_ed25519:
            sig    = auth.get("sig", "")
            pubkey = auth.get("pubkey", "")
            if not sig or not pubkey:
                if is_handshake:
                    return True, "ok-handshake-no-sig"
                return False, "Отсутствует Ed25519-подпись"
            # ── PeerKeyRegistry: проверяем что pubkey зарегистрирован ────────
            # Handshake-методы пропускаем (bootstrap: ещё не знаем ключ)
            # Собственный pubkey ноды тоже пропускаем (self-signed вызовы панели)
            if self._peer_registry is not None and not is_handshake:
                known_node = self._peer_registry.lookup_by_pubkey(pubkey)
                own_pubkey = self._own_pubkey  # может быть None
                is_own = (own_pubkey is not None and pubkey.lower() == own_pubkey.lower())
                if known_node is None and not is_own:
                    return False, "Pubkey не в реестре пиров"
            body = _canonical_body(envelope)
            if not self.verify_ed25519(body, sig, pubkey):
                return False, "Неверная Ed25519-подпись"

        return True, "ok"


# ══════════════════════════════════════════════════════════════════════════════
# Подписчик (клиент)
# ══════════════════════════════════════════════════════════════════════════════

class AuthSigner:
    """Добавляет auth-блок к исходящим сообщениям."""

    def __init__(
        self,
        node_keys: NodeKeys | None = None,
        shared_secret: str = "",
    ) -> None:
        self._keys  = node_keys
        self._secret = shared_secret.encode() if shared_secret else b""

    def sign_envelope(self, envelope: dict) -> dict:
        """
        Дополнить envelope блоком auth.
        Envelope НЕ должен содержать поле auth до вызова (оно будет добавлено).
        """
        auth: dict[str, Any] = {
            "timestamp": time.time(),
            "nonce":     str(uuid.uuid4()),
        }

        # Ed25519
        if self._keys and _HAS_CRYPTO and self._keys._private_key is not None:
            # Подписываем тело БЕЗ auth (auth ещё пустой — OK)
            body = _canonical_body({**envelope, "auth": auth})
            sig  = self._keys.sign(body)
            auth["sig"]    = sig.hex()
            auth["pubkey"] = self._keys.public_key_hex()

        # HMAC
        if self._secret:
            body = _canonical_body({**envelope, "auth": auth})
            auth["hmac"] = hmac.new(self._secret, body, hashlib.sha256).hexdigest()

        envelope["auth"] = auth
        return envelope


# ══════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ══════════════════════════════════════════════════════════════════════════════

def _canonical_body(envelope: dict) -> bytes:
    """
    Детерминированная JSON-сериализация конверта (без поля auth.hmac/sig).
    Используется как тело для подписи.
    """
    # Делаем копию без подписи, чтобы избежать циклической зависимости
    clean = {k: v for k, v in envelope.items() if k != "auth"}
    # ВАЖНО: исключаем не только hmac/sig, но и pubkey —
    # signer считает подпись ДО того, как кладёт pubkey в auth,
    # поэтому канон-форма не должна содержать pubkey, иначе
    # verifier получит другой body → "Неверная Ed25519-подпись".
    auth_copy = {
        k: v
        for k, v in envelope.get("auth", {}).items()
        if k not in ("hmac", "sig", "pubkey")
    }
    if auth_copy:
        clean["auth"] = auth_copy
    return json.dumps(clean, sort_keys=True, separators=(",", ":")).encode()


def make_auth_pair(
    cfg: dict,
    key_dir: str = ".swarm_keys",
    peer_registry=None,
) -> tuple[AuthSigner, AuthVerifier]:
    """
    Фабрика: читает секцию `auth` из config и возвращает (signer, verifier).

    config.yaml пример:
        auth:
          enabled: true
          shared_secret: "my-secret"   # HMAC
          require_ed25519: true         # Ed25519
          key_dir: ".swarm_keys"
    """
    auth_cfg       = cfg.get("auth", {})
    enabled        = auth_cfg.get("enabled", False)
    secret         = auth_cfg.get("shared_secret", "") if enabled else ""
    req_ed25519    = auth_cfg.get("require_ed25519", False) and enabled
    key_dir_path   = auth_cfg.get("key_dir", key_dir)

    keys: NodeKeys | None = None
    if enabled and (req_ed25519 or auth_cfg.get("generate_keys", True)):
        keys = NodeKeys(key_dir_path)
        keys.load_or_generate()

    signer   = AuthSigner(node_keys=keys, shared_secret=secret)
    own_pubkey = keys.public_key_hex() if keys else ""
    verifier = AuthVerifier(shared_secret=secret, require_ed25519=req_ed25519, peer_registry=peer_registry, own_pubkey=own_pubkey)
    return signer, verifier
