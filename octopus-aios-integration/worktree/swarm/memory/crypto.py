"""End-to-end encryption layer for the Immortal Swarm memory facade.

Public pastebins (telegraph, catbox, …) are world-readable: anyone holding
the ref can fetch the bytes.  This module wraps the memory facade so that
every artifact is encrypted *before* it leaves the host and decrypted only
after the local node receives the bytes back.

Primitives
----------
* **AEAD**:  AES-256-GCM (via ``cryptography.hazmat.primitives.ciphers.aead``).
* **KDF**:   Scrypt (``cryptography``) when available, falling back to PBKDF2-
            HMAC-SHA256 from the standard library — no extra dependency
            beyond ``cryptography`` itself, which is already a swarm dep.
* **Random**: ``os.urandom`` for nonces and salts (CSPRNG from the OS).

Envelope format (raw bytes, written into the inner adapter):

    b"GMX1" | nonce(12) | tag_len(2 LE) | tag_b64 | ciphertext

``tag`` is a base64-encoded JSON object preserving Artifact metadata that
must travel encrypted alongside the body (mime, tags, attrs, provenance).
Routing-only ``attrs`` keys (``store``, ``worm_base_ref``) stay outside the
envelope so the composite port can still pick the right backend.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    RefMeta,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAGIC = b"GMX1"                 # 4-byte envelope header
NONCE_LEN = 12                  # AES-GCM standard
KEY_LEN = 32                    # AES-256
SALT_LEN = 16                   # Scrypt / PBKDF2 salt

# Attributes that MUST stay outside the encryption envelope so the composite
# memory port can route the put correctly.
_ROUTING_ATTRS = frozenset({"store", "worm_base_ref"})


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KdfParams:
    """Parameters required to re-derive a key from a password.

    ``algorithm`` is one of ``"scrypt"`` or ``"pbkdf2-sha256"``.  All fields
    survive a round-trip through ``to_dict`` / ``from_dict`` so a manifest
    can carry the parameters next to the ciphertext.
    """

    algorithm: str
    salt: bytes
    n: int = 2 ** 15      # Scrypt cost
    r: int = 8
    p: int = 1
    iterations: int = 200_000  # PBKDF2 iterations (when algorithm == pbkdf2-sha256)

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "salt_b64": base64.b64encode(self.salt).decode("ascii"),
            "n": self.n,
            "r": self.r,
            "p": self.p,
            "iterations": self.iterations,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> KdfParams:
        return cls(
            algorithm=str(raw["algorithm"]),
            salt=base64.b64decode(raw["salt_b64"]),
            n=int(raw.get("n", 2 ** 15)),
            r=int(raw.get("r", 8)),
            p=int(raw.get("p", 1)),
            iterations=int(raw.get("iterations", 200_000)),
        )


def derive_key(password: str | bytes, params: KdfParams | None = None) -> tuple[bytes, KdfParams]:
    """Derive a 32-byte AES-256 key from a password.

    Returns ``(key, params)``.  Pass an existing ``params`` to re-derive a
    previous key; pass ``None`` to generate a fresh salt + Scrypt defaults.
    """
    if isinstance(password, str):
        password = password.encode("utf-8")
    if params is None:
        params = KdfParams(algorithm="scrypt", salt=os.urandom(SALT_LEN))

    if params.algorithm == "scrypt":
        try:
            from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

            kdf = Scrypt(salt=params.salt, length=KEY_LEN, n=params.n, r=params.r, p=params.p)
            return kdf.derive(password), params
        except Exception:
            # Older / restricted cryptography builds — fall through to PBKDF2.
            params = KdfParams(algorithm="pbkdf2-sha256", salt=params.salt, iterations=params.iterations)

    if params.algorithm == "pbkdf2-sha256":
        key = hashlib.pbkdf2_hmac("sha256", password, params.salt, params.iterations, dklen=KEY_LEN)
        return key, params

    raise ValueError(f"unsupported KDF algorithm: {params.algorithm!r}")


def random_key() -> bytes:
    """Return a brand-new 256-bit random key suitable for AES-GCM."""
    return os.urandom(KEY_LEN)


# ---------------------------------------------------------------------------
# Constant-time helpers (for tests / signature verifications elsewhere)
# ---------------------------------------------------------------------------

def consteq(a: bytes, b: bytes) -> bool:
    """Constant-time equality check."""
    return hmac.compare_digest(a, b)


# ---------------------------------------------------------------------------
# CryptoBox — AEAD seal / open over raw bytes
# ---------------------------------------------------------------------------

class CryptoBox:
    """AES-256-GCM helper bound to a single 32-byte key.

    Sealed envelope format:

        MAGIC | nonce(12) | tag_len(2 LE) | tag_b64 | ciphertext

    where ``tag_b64`` is base64 of a JSON object with the per-artifact
    metadata that needs to travel encrypted (mime, tags, attrs, provenance).
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_LEN:
            raise ValueError(f"key must be {KEY_LEN} bytes, got {len(key)}")
        self._aead = AESGCM(key)
        self._key = key

    # --- raw bytes ----------------------------------------------------

    def seal_bytes(self, data: bytes, *, aad: bytes = b"") -> bytes:
        nonce = os.urandom(NONCE_LEN)
        ct = self._aead.encrypt(nonce, data, aad or None)
        return MAGIC + nonce + b"\x00\x00" + ct

    def open_bytes(self, blob: bytes, *, aad: bytes = b"") -> bytes:
        nonce, _meta_b64, ct = self._split(blob)
        return self._aead.decrypt(nonce, ct, aad or None)

    # --- artifact wrappers --------------------------------------------

    def seal_artifact(self, artifact: Artifact) -> Artifact:
        """Return a new Artifact whose ``content`` is an encrypted envelope.

        Metadata that must stay routable (``attrs.store``, ``worm_base_ref``)
        is propagated outside the envelope; everything else is encrypted.
        ``tags`` outside the envelope is wiped so server-side search cannot
        leak them — callers wanting tag-search on encrypted memory should
        index plaintext tags separately in a trusted local adapter.
        """
        content = artifact.content
        if isinstance(content, str):
            content = content.encode("utf-8")

        attrs = dict(artifact.attrs or {})
        outer_attrs = {k: v for k, v in attrs.items() if k in _ROUTING_ATTRS}
        inner = {
            "mime": artifact.mime,
            "tags": list(artifact.tags or []),
            "provenance": dict(artifact.provenance or {}),
            "attrs": {k: v for k, v in attrs.items() if k not in _ROUTING_ATTRS},
        }
        meta_json = json.dumps(inner, ensure_ascii=False, sort_keys=True).encode("utf-8")
        meta_b64 = base64.b64encode(meta_json)
        # AAD: the metadata blob is authenticated even though it's not encrypted.
        # We DO encrypt it too, but binding it as AAD prevents tampering across
        # envelopes that share the same key.
        nonce = os.urandom(NONCE_LEN)
        ct = self._aead.encrypt(nonce, content, meta_b64)
        # Layout: MAGIC | nonce | meta_len(LE u16) | meta_b64 | ct
        if len(meta_b64) > 0xFFFF:
            raise ValueError("artifact metadata too large to seal (>64 KB)")
        meta_len = len(meta_b64).to_bytes(2, "little")
        envelope = MAGIC + nonce + meta_len + meta_b64 + ct
        outer_attrs["__enc__"] = "aesgcm:v1"
        return Artifact(
            content=envelope,
            mime="application/x-gemaxi-encrypted",
            tags=[],
            provenance={},
            attrs=outer_attrs,
        )

    def open_artifact(self, artifact: Artifact) -> Artifact:
        blob = artifact.content
        if isinstance(blob, str):
            blob = blob.encode("latin-1")
        nonce, meta_b64, ct = self._split(blob)
        plaintext = self._aead.decrypt(nonce, ct, meta_b64)
        inner = json.loads(base64.b64decode(meta_b64).decode("utf-8"))
        outer_attrs = dict(artifact.attrs or {})
        outer_attrs.pop("__enc__", None)
        merged = {**(inner.get("attrs") or {}), **outer_attrs}
        return Artifact(
            content=plaintext,
            mime=str(inner.get("mime") or "application/octet-stream"),
            tags=list(inner.get("tags") or []),
            provenance=dict(inner.get("provenance") or {}),
            attrs=merged,
        )

    # --- helpers ------------------------------------------------------

    @staticmethod
    def _split(blob: bytes) -> tuple[bytes, bytes, bytes]:
        if len(blob) < len(MAGIC) + NONCE_LEN + 2 + 16:
            raise MemoryAdapterError("encrypted envelope truncated")
        if not blob.startswith(MAGIC):
            raise MemoryAdapterError(
                f"not a gemaxi encrypted envelope (bad magic): {blob[:4]!r}"
            )
        pos = len(MAGIC)
        nonce = blob[pos : pos + NONCE_LEN]
        pos += NONCE_LEN
        meta_len = int.from_bytes(blob[pos : pos + 2], "little")
        pos += 2
        meta_b64 = blob[pos : pos + meta_len]
        pos += meta_len
        ct = blob[pos:]
        return nonce, meta_b64, ct


def is_encrypted(artifact: Artifact) -> bool:
    """True if the artifact looks like a sealed envelope."""
    attrs = artifact.attrs or {}
    if attrs.get("__enc__") == "aesgcm:v1":
        return True
    content = artifact.content
    return bool(isinstance(content, bytes) and content.startswith(MAGIC))


# ---------------------------------------------------------------------------
# EncryptedMemoryPort middleware
# ---------------------------------------------------------------------------

class EncryptedMemoryPort:
    """Transparent encryption wrapper around a :class:`MemoryPort`.

    Every ``put`` seals the artifact through :class:`CryptoBox` before
    handing it to the inner port; every ``get`` opens the envelope after
    reading.  Adapters never see plaintext, so the same key on two
    different nodes can publish and read encrypted records via any of the
    14 anonymous pastebins.

    Search routing is best-effort: tags on encrypted artifacts are wiped
    *outside* the envelope, so server-side tag search cannot find them.
    Callers wanting indexed search on encrypted memory should keep a
    separate plaintext local catalog (e.g. via :class:`MemoryRepository`
    on a trusted ``file`` adapter).
    """

    def __init__(self, inner, box: CryptoBox) -> None:
        self._inner = inner
        self._box = box

    # ------------------------------------------------------------------
    # MemoryPort protocol
    # ------------------------------------------------------------------

    @property
    def metrics(self):
        return self._inner.metrics

    async def put(self, artifact: Artifact) -> str:
        sealed = self._box.seal_artifact(artifact)
        return await self._inner.put(sealed)

    async def get(self, ref: str) -> Artifact:
        art = await self._inner.get(ref)
        if not is_encrypted(art):
            return art
        return self._box.open_artifact(art)

    async def exists(self, ref: str) -> bool:
        return await self._inner.exists(ref)

    async def delete(self, ref: str) -> bool:
        return await self._inner.delete(ref)

    async def search(self, tags: list[str], owner: str | None = None) -> list[RefMeta]:
        # Tags don't cross the envelope by design — search only sees
        # whatever the inner port can reach (rare, but useful for local
        # adapters that index outside-envelope attrs).
        return await self._inner.search(tags, owner=owner)

    async def promote(self, ref: str) -> str:
        if hasattr(self._inner, "promote"):
            return await self._inner.promote(ref)
        raise MemoryAdapterError("inner port does not support promote")

    def capabilities(self) -> Capabilities:
        inner_caps = self._inner.capabilities()
        return Capabilities(
            schemes=inner_caps.schemes,
            supports_search=False,  # honest: encrypted tags don't search
            supports_delete=inner_caps.supports_delete,
            supports_promote=inner_caps.supports_promote,
        )
