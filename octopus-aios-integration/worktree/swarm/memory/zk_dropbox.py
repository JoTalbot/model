"""Zero-knowledge dropbox -- keys live in the URL fragment, never on a paste.

Every pastebin we route through is world-readable: anyone holding a
plain :class:`FileDropbox` manifest ref can fetch the bytes.  This module
moves the threat boundary one notch tighter: the swarm holds *only
ciphertext*, and the decryption key travels in the URL fragment (the
``#key=...`` part) of the share link.  HTTP fragments never leave the
browser / client -- so even if every cloud we mirror to gets subpoenaed
tomorrow, the resulting data is unreadable.

Wire format
~~~~~~~~~~~

::

    zk:<inner_dropbox_ref>#key=<base64-url-32B>[&algo=aesgcm-v1]

* ``<inner_dropbox_ref>`` is the standard ``FileDropbox`` ref returned
  by :meth:`FileDropbox.upload`.
* ``<base64-url-32B>`` is the 256-bit AES-GCM key, URL-safe-base64 with
  ``=`` stripping.
* ``algo=aesgcm-v1`` is the only supported algorithm right now and is
  encoded for forward compatibility; older keys without ``algo`` are
  treated as v1.

Usage
~~~~~

.. code-block:: python

    zkdrop = ZkDropbox(file_dropbox)
    share_link = await zkdrop.upload("/path/big-backup.zip")
    # share_link -> zk:dropbox:ref:catbox:https://...json#key=...

    await zkdrop.download(share_link, "/restore/back.zip")

Pair with the QR exporter (``memory bootstrap-qr``) for sneakernet
recovery: the QR encodes the whole ``zk:...#key=...`` string, so a
single photograph carries both location and unlock secret.

Security caveats
~~~~~~~~~~~~~~~~

* Anyone who reads the share link in plaintext (logs, screenshots,
  notifications) can also decrypt.  Treat it like a password.
* Anonymous storage providers can still see *that* a chunk was
  uploaded, and how big it was -- traffic analysis is out of scope.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from swarm.memory.crypto import CryptoBox, random_key

ZK_SCHEME = "zk"
SUPPORTED_ALGOS = ("aesgcm-v1",)


# ---------------------------------------------------------------------------
# Link encoding
# ---------------------------------------------------------------------------


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


@dataclass(frozen=True)
class ZkShareLink:
    """Parsed view of a zero-knowledge share link."""

    inner_ref: str
    key: bytes
    algo: str = "aesgcm-v1"

    def to_string(self) -> str:
        return (
            f"{ZK_SCHEME}:{self.inner_ref}"
            f"#key={_b64u_encode(self.key)}&algo={self.algo}"
        )

    @classmethod
    def parse(cls, link: str) -> ZkShareLink:
        if not link.startswith(f"{ZK_SCHEME}:"):
            raise ValueError(f"not a zk: share link: {link[:32]!r}...")
        raw = link[len(ZK_SCHEME) + 1 :]
        if "#" not in raw:
            raise ValueError("zk share link is missing #key= fragment")
        inner_ref, _, fragment = raw.partition("#")
        params = parse_qs(fragment, keep_blank_values=False)
        key_list = params.get("key")
        if not key_list or not key_list[0]:
            raise ValueError("zk share link missing key= parameter")
        algo_list = params.get("algo") or ["aesgcm-v1"]
        algo = algo_list[0]
        if algo not in SUPPORTED_ALGOS:
            raise ValueError(f"unsupported algo {algo!r} (supported: {SUPPORTED_ALGOS})")
        key = _b64u_decode(key_list[0])
        if len(key) != 32:
            raise ValueError(f"zk key must be 32 bytes, got {len(key)}")
        return cls(inner_ref=inner_ref, key=key, algo=algo)


# ---------------------------------------------------------------------------
# ZkDropbox
# ---------------------------------------------------------------------------


class ZkDropbox:
    """Wrap a :class:`FileDropbox` with client-side AES-256-GCM."""

    def __init__(self, file_dropbox) -> None:
        self._inner = file_dropbox

    async def upload(
        self,
        path_or_bytes,
        *,
        name: str | None = None,
        key: bytes | None = None,
        **kwargs: Any,
    ) -> str:
        """Encrypt the file under a fresh (or supplied) key and upload it.

        Returns the ``zk:<inner_ref>#key=...`` share link.  Keep that
        string private -- handing it over is equivalent to handing over
        the file.
        """
        material_name, plaintext = _read_payload(path_or_bytes)
        the_key = key if key is not None else random_key()
        if len(the_key) != 32:
            raise ValueError("zk key must be 32 bytes")
        box = CryptoBox(the_key)
        ciphertext = box.seal_bytes(plaintext)

        upload_name = name or f"{material_name or 'payload'}.zkenc"
        report = await self._inner.upload(ciphertext, name=upload_name, **kwargs)
        inner_ref = type(self._inner).dropbox_ref(report.manifest_ref)
        return ZkShareLink(inner_ref=inner_ref, key=the_key).to_string()

    async def download(
        self,
        share_link: str,
        dst,
        *,
        mirrors: list[str] | None = None,
    ) -> Path:
        """Reverse :meth:`upload`: download ciphertext, decrypt, write plaintext."""
        link = ZkShareLink.parse(share_link)
        ciphertext = await _download_to_bytes(self._inner, link.inner_ref, mirrors)
        box = CryptoBox(link.key)
        plaintext = box.open_bytes(ciphertext)
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes(plaintext)
        return dst_path

    async def info(self, share_link: str, *, mirrors: list[str] | None = None) -> dict:
        """Return the inner-dropbox info dict + ``algo`` for the share link.

        Never touches the key -- the report is identical to the plain
        :meth:`FileDropbox.info` plus a confirmation that the link was
        well-formed.
        """
        link = ZkShareLink.parse(share_link)
        ref_arg: Any = (
            [link.inner_ref, *mirrors] if mirrors else link.inner_ref
        )
        info = await self._inner.info(ref_arg)
        info["zk"] = {"algo": link.algo, "key_bytes": len(link.key)}
        return info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_payload(path_or_bytes) -> tuple[str | None, bytes]:
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return None, bytes(path_or_bytes)
    if isinstance(path_or_bytes, (str, Path)):
        p = Path(path_or_bytes)
        return p.name, p.read_bytes()
    raise TypeError(f"unsupported payload type {type(path_or_bytes).__name__}")


async def _download_to_bytes(inner, inner_ref: str, mirrors: list[str] | None) -> bytes:
    """Fallback path: write to a temp file, read it back, unlink.

    FileDropbox.download streams to disk by design; some adapters won't
    have a bytes-returning shortcut.  This wrapper keeps ZkDropbox
    deterministic without forcing a FileDropbox API change.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(prefix="zk-", suffix=".enc", delete=False) as fh:
        tmp_path = fh.name
    try:
        if mirrors:
            await inner.download([inner_ref, *mirrors], tmp_path)
        else:
            await inner.download(inner_ref, tmp_path)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


__all__ = ["SUPPORTED_ALGOS", "ZK_SCHEME", "ZkDropbox", "ZkShareLink"]
