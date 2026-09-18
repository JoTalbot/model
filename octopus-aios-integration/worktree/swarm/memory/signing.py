"""Ed25519 signing layer for the Immortal Swarm memory facade.

Encryption (``swarm.memory.crypto``) gives **confidentiality**: a
pastebin holding the ciphertext cannot read it.  Signing gives
**authenticity**: the swarm can prove which agent wrote a given record
and detect any later tampering — even when the underlying storage is
hostile.

Primitives
----------
* **Algorithm**:   Ed25519 (``cryptography.hazmat.primitives.asymmetric.ed25519``)
* **Encoding**:    raw 32-byte public keys, 64-byte signatures, both
                   base64-encoded inside the Artifact ``attrs``.
* **Identity**:    each :class:`SigningKey` carries a stable hex
                   ``key_id`` (BLAKE2s of the public key, 16 hex chars)
                   so callers can keep a small ring of trusted authors
                   without dragging in PKI.

Signed-envelope shape
---------------------
``Artifact.attrs`` gains the ``__sig__`` key on a signed put:

    attrs["__sig__"] = {
        "alg": "ed25519",
        "key_id": "<16-hex>",
        "pubkey_b64": "<32-byte raw key>",
        "sig_b64": "<64-byte signature>",
        "canon": "v1",
    }

The signature is over a deterministic JSON canonicalisation of the
artifact (mime, sorted tags, sorted provenance, sorted attrs minus the
``__sig__`` slot itself, and the content as base64).  ``canon`` records
the version so future canonicalisers can coexist.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

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

from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    RefMeta,
)

SIG_ATTR = "__sig__"
ALG = "ed25519"
CANON_VERSION = "v1"


# ---------------------------------------------------------------------------
# Key wrappers
# ---------------------------------------------------------------------------

def _key_id(pub_bytes: bytes) -> str:
    return hashlib.blake2s(pub_bytes, digest_size=8).hexdigest()


@dataclass
class VerifyKey:
    """Public Ed25519 key with a deterministic short id."""

    pub_bytes: bytes  # 32 raw bytes

    def __post_init__(self) -> None:
        if len(self.pub_bytes) != 32:
            raise ValueError(
                f"Ed25519 public key must be 32 bytes, got {len(self.pub_bytes)}"
            )
        self._pub = Ed25519PublicKey.from_public_bytes(self.pub_bytes)
        self.key_id = _key_id(self.pub_bytes)

    @classmethod
    def from_b64(cls, b64: str) -> VerifyKey:
        return cls(pub_bytes=base64.b64decode(b64))

    def to_b64(self) -> str:
        return base64.b64encode(self.pub_bytes).decode("ascii")

    def verify(self, signature: bytes, data: bytes) -> bool:
        try:
            self._pub.verify(signature, data)
            return True
        except InvalidSignature:
            return False


@dataclass
class SigningKey:
    """Ed25519 private key + bundled :class:`VerifyKey`."""

    priv_bytes: bytes  # 32 raw bytes

    def __post_init__(self) -> None:
        if len(self.priv_bytes) != 32:
            raise ValueError(
                f"Ed25519 private key must be 32 bytes, got {len(self.priv_bytes)}"
            )
        self._priv = Ed25519PrivateKey.from_private_bytes(self.priv_bytes)
        pub_bytes = self._priv.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self.verify_key = VerifyKey(pub_bytes=pub_bytes)

    @classmethod
    def generate(cls) -> SigningKey:
        priv = Ed25519PrivateKey.generate()
        return cls(
            priv_bytes=priv.private_bytes(
                Encoding.Raw, PrivateFormat.Raw, NoEncryption()
            )
        )

    @classmethod
    def from_b64(cls, b64: str) -> SigningKey:
        return cls(priv_bytes=base64.b64decode(b64))

    def to_b64(self) -> str:
        return base64.b64encode(self.priv_bytes).decode("ascii")

    @property
    def key_id(self) -> str:
        return self.verify_key.key_id

    def sign(self, data: bytes) -> bytes:
        return self._priv.sign(data)


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------

def _canonical_bytes(artifact: Artifact, *, drop_sig: bool = True) -> bytes:
    """Deterministic bytes representation of an artifact, signature-stripped."""
    content = artifact.content
    if isinstance(content, str):
        content = content.encode("utf-8")
    attrs = dict(artifact.attrs or {})
    if drop_sig:
        attrs.pop(SIG_ATTR, None)
    body = {
        "v": CANON_VERSION,
        "mime": artifact.mime,
        "tags": sorted(list(artifact.tags or [])),
        "provenance": dict(artifact.provenance or {}),
        "attrs": attrs,
        "content_b64": base64.b64encode(content).decode("ascii"),
    }
    return json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")


# ---------------------------------------------------------------------------
# Sign / verify helpers
# ---------------------------------------------------------------------------

def sign_artifact(artifact: Artifact, key: SigningKey) -> Artifact:
    """Return a copy of ``artifact`` with an embedded signature block."""
    canon = _canonical_bytes(artifact)
    sig = key.sign(canon)
    sig_block = {
        "alg": ALG,
        "key_id": key.key_id,
        "pubkey_b64": key.verify_key.to_b64(),
        "sig_b64": base64.b64encode(sig).decode("ascii"),
        "canon": CANON_VERSION,
    }
    new_attrs = dict(artifact.attrs or {})
    new_attrs[SIG_ATTR] = sig_block
    return Artifact(
        content=artifact.content,
        mime=artifact.mime,
        tags=list(artifact.tags or []),
        provenance=dict(artifact.provenance or {}),
        attrs=new_attrs,
    )


def is_signed(artifact: Artifact) -> bool:
    return bool((artifact.attrs or {}).get(SIG_ATTR))


def signer_info(artifact: Artifact) -> dict[str, Any]:
    block = (artifact.attrs or {}).get(SIG_ATTR) or {}
    return {
        "alg": block.get("alg"),
        "key_id": block.get("key_id"),
        "pubkey_b64": block.get("pubkey_b64"),
        "canon": block.get("canon"),
    }


def verify_artifact(
    artifact: Artifact,
    *,
    trusted: dict[str, VerifyKey] | None = None,
    require_known_signer: bool = False,
) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for the artifact's signature.

    ``trusted`` is a ``{key_id -> VerifyKey}`` ring; when supplied, the
    function additionally checks that the embedded public key matches
    the trusted one for that key_id.

    ``require_known_signer=True`` rejects artifacts whose key_id is not
    in ``trusted`` (default behaviour is "verify embedded key only").
    """
    block = (artifact.attrs or {}).get(SIG_ATTR)
    if not block:
        return False, "no signature"
    if block.get("alg") != ALG:
        return False, f"unsupported alg: {block.get('alg')!r}"
    if block.get("canon") != CANON_VERSION:
        return False, f"unknown canon version: {block.get('canon')!r}"
    try:
        pub_bytes = base64.b64decode(block["pubkey_b64"])
        sig = base64.b64decode(block["sig_b64"])
    except Exception as exc:
        return False, f"signature decode error: {exc}"
    expected_kid = _key_id(pub_bytes)
    if block.get("key_id") != expected_kid:
        return False, "key_id mismatch with embedded public key"
    if trusted is not None and expected_kid in trusted:
        if trusted[expected_kid].pub_bytes != pub_bytes:
            return False, "trusted ring key mismatch"
    elif require_known_signer:
        return False, "signer not in trusted ring"
    try:
        verify_key = VerifyKey(pub_bytes=pub_bytes)
    except ValueError as exc:
        return False, str(exc)
    canon = _canonical_bytes(artifact)
    if not verify_key.verify(sig, canon):
        return False, "signature verification failed"
    return True, "ok"


# ---------------------------------------------------------------------------
# SignedMemoryPort middleware
# ---------------------------------------------------------------------------

class SignedMemoryPort:
    """Wrap a MemoryPort so every put is signed and every get is verified.

    * Records produced through this port carry an Ed25519 signature in
      ``attrs[__sig__]``.
    * On ``get``, the embedded signature is checked.  Mismatches raise
      :class:`MemoryAdapterError` so corrupted or hostile bytes can't
      leak into downstream code.
    * Optional ``trusted`` ring lets a node accept only records signed
      by known peers.  ``require_known_signer=True`` makes that strict.
    * Plain (unsigned) artifacts can flow through unchanged when
      ``allow_unsigned=True`` (default ``False``).  Useful while migrating
      a legacy corpus.
    """

    def __init__(
        self,
        inner,
        signing_key: SigningKey,
        *,
        trusted: dict[str, VerifyKey] | None = None,
        require_known_signer: bool = False,
        allow_unsigned: bool = False,
    ) -> None:
        self._inner = inner
        self._signing_key = signing_key
        self._trusted = dict(trusted or {})
        self._require_known_signer = require_known_signer
        self._allow_unsigned = allow_unsigned

    # ------------------------------------------------------------------
    # Trusted-ring management
    # ------------------------------------------------------------------

    def trust(self, vk: VerifyKey) -> None:
        self._trusted[vk.key_id] = vk

    def untrust(self, key_id: str) -> bool:
        return self._trusted.pop(key_id, None) is not None

    @property
    def trusted_ids(self) -> set[str]:
        return set(self._trusted.keys())

    # ------------------------------------------------------------------
    # MemoryPort protocol
    # ------------------------------------------------------------------

    @property
    def metrics(self):
        return self._inner.metrics

    async def put(self, artifact: Artifact) -> str:
        signed = sign_artifact(artifact, self._signing_key)
        return await self._inner.put(signed)

    async def get(self, ref: str) -> Artifact:
        artifact = await self._inner.get(ref)
        if not is_signed(artifact):
            if self._allow_unsigned:
                return artifact
            raise MemoryAdapterError(f"unsigned artifact rejected: {ref}")
        ok, reason = verify_artifact(
            artifact,
            trusted=self._trusted or None,
            require_known_signer=self._require_known_signer,
        )
        if not ok:
            raise MemoryAdapterError(
                f"signature verification failed for {ref}: {reason}"
            )
        return artifact

    async def exists(self, ref: str) -> bool:
        return await self._inner.exists(ref)

    async def delete(self, ref: str) -> bool:
        return await self._inner.delete(ref)

    async def search(self, tags: list[str], owner: str | None = None) -> list[RefMeta]:
        return await self._inner.search(tags, owner=owner)

    async def promote(self, ref: str) -> str:
        if hasattr(self._inner, "promote"):
            return await self._inner.promote(ref)
        raise MemoryAdapterError("inner port does not support promote")

    def capabilities(self) -> Capabilities:
        return self._inner.capabilities()
