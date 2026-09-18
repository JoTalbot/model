"""Free anonymous online storage adapters — no auth required.

Each adapter wraps remote content in a JSON envelope so that binary data,
MIME type, tags, provenance and attrs all survive the round-trip through
text-only services (dpaste, ix.io, telegraph, …).

Envelope format (stored as UTF-8 JSON on the remote service)::

    {
        "__gemaxi_v1__": true,
        "mime": "application/octet-stream",
        "tags": ["..."],
        "provenance": {...},
        "attrs": {...},
        "data_b64": "<base64-encoded raw bytes>"
    }

Supported schemes and backing services:

* ``nullpointer`` — https://0x0.st         (binary; **uploads may be disabled**)
* ``catbox``      — https://catbox.moe     (binary, 200 MB, permanent)
* ``fileio``      — https://file.io        (binary, 100 MB, auto-deletes)
* ``dpaste``      — https://dpaste.org     (text envelope, 1 MB; **service may be offline** — see adapter errors)
* ``ixio``        — http://ix.io           (text envelope, ~64 KB)
* ``telegraph``   — https://telegra.ph     (wiki-like, permanent, anonymous)
* ``rentry``      — https://rentry.co      (markdown, permanent, edit-code)
* ``pasteee``     — https://paste.ee       (text; **requires** free Application key)
* ``termbin``     — termbin.com:9999/tcp   (raw TCP pastebin)
* ``tmpfiles``    — https://tmpfiles.org   (binary, 1 hour expiry)
* ``transfersh``  — https://transfer.sh    (binary, 14 days)
* ``sprunge``     — http://sprunge.us      (text, plain curl POST)
* ``pasters``     — https://paste.rs       (text, no JS, no auth)
* ``hastebin``    — https://hastebin.com   (text, ~400 KB)
* ``pixeldrain``  — https://pixeldrain.com (binary, 20 GB, anonymous)
* ``filebin``     — https://filebin.net    (binary, bin-style, 6-day default)
* ``litterbox``   — https://litterbox.catbox.moe (binary, 1h-72h temp)
* ``bashupload``  — https://bashupload.com (binary, 3 days)
* ``clbin``       — https://clbin.com      (text, ix.io alternative)
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import uuid
from typing import Any

import httpx

from swarm.memory.http_fetch_guard import guard_http_client
from swarm.memory.ref_parse import make_ref, parse_ref
from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    RefMeta,
    RefNotFoundError,
)

_ENVELOPE_KEY = "__gemaxi_v1__"


def _wrap_cloud_client(
    client: httpx.AsyncClient | None,
    timeout: float,
    fetch_hosts: frozenset[str] | None,
) -> httpx.AsyncClient:
    inner = client or httpx.AsyncClient(timeout=timeout)
    return guard_http_client(inner, fetch_hosts)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def _pack(artifact: Artifact) -> bytes:
    """Wrap an Artifact into a JSON envelope (bytes, UTF-8)."""
    content = artifact.content
    if isinstance(content, str):
        content = content.encode("utf-8")
    envelope: dict[str, Any] = {
        _ENVELOPE_KEY: True,
        "mime": artifact.mime,
        "tags": list(artifact.tags or []),
        "provenance": dict(artifact.provenance or {}),
        "attrs": dict(artifact.attrs or {}),
        "data_b64": base64.b64encode(content).decode("ascii"),
    }
    return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def _unpack(raw: bytes) -> Artifact:
    """Reconstruct an Artifact from a JSON envelope.

    Falls back to a plain binary Artifact when the envelope marker is absent,
    so manually uploaded files remain accessible.
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Artifact(content=raw, mime="application/octet-stream")
    if not isinstance(payload, dict) or not payload.get(_ENVELOPE_KEY):
        return Artifact(content=raw, mime="application/octet-stream")
    try:
        content = base64.b64decode(payload["data_b64"])
    except Exception as exc:
        raise MemoryAdapterError(f"envelope data_b64 decode error: {exc}") from exc
    return Artifact(
        content=content,
        mime=payload.get("mime", "application/octet-stream"),
        tags=list(payload.get("tags") or []),
        provenance=dict(payload.get("provenance") or {}),
        attrs=dict(payload.get("attrs") or {}),
    )


def _make_filename() -> str:
    return f"gemaxi_{uuid.uuid4().hex[:8]}.json"


def _no_caps(scheme: str) -> Capabilities:
    return Capabilities(
        schemes=frozenset({scheme}),
        supports_search=False,
        supports_delete=False,
        supports_promote=False,
    )


# ---------------------------------------------------------------------------
# 1. NullpointerAdapter — 0x0.st
# ---------------------------------------------------------------------------

class NullpointerAdapter:
    """Anonymous uploads to https://0x0.st (nullpointer).

    * No authentication.
    * Binary-safe via JSON envelope.
    * Max 512 MB; files retained 30 days–1 year (smaller = longer).
    * Deletion not supported anonymously.

    .. note::
        Uploads may return **503** when the operator disables the service
        (e.g. abuse). Prefer ``pasteee`` or ``pasters`` for text payloads.

    Ref format: ``ref:nullpointer:<full_url>``
    e.g.  ``ref:nullpointer:https://0x0.st/AbCd``
    """

    scheme: str = "nullpointer"
    _API = "https://0x0.st"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 60.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        try:
            resp = await self._client.post(
                self._API,
                files={"file": (_make_filename(), data, "application/json")},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"nullpointer upload error: {exc}") from exc
        if not resp.is_success:
            snippet = (resp.text or "")[:400]
            extra = ""
            low = snippet.lower()
            if resp.status_code in (403, 503) or "disabled" in low or "spam" in low:
                extra = (
                    " Try `--store pasters` or `catbox` (no API key). "
                    "For paste.ee set PASTE_EE_API_KEY or pasteee_api_key in config."
                )
            raise MemoryAdapterError(
                f"nullpointer HTTP {resp.status_code}: {snippet[:200]}.{extra}"
            )
        url = resp.text.strip()
        if not url.startswith(("https://", "http://")):
            raise MemoryAdapterError(f"nullpointer unexpected response: {url[:120]}")
        return make_ref("nullpointer", url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"nullpointer download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"nullpointer HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("nullpointer")


# ---------------------------------------------------------------------------
# 2. CatboxAdapter — catbox.moe
# ---------------------------------------------------------------------------

class CatboxAdapter:
    """Anonymous uploads to https://catbox.moe.

    * No authentication (userhash left empty).
    * Binary-safe via JSON envelope.
    * Max 200 MB; files stored permanently.
    * Deletion not supported without a user hash.

    Ref format: ``ref:catbox:<full_url>``
    e.g.  ``ref:catbox:https://files.catbox.moe/abc123.json``
    """

    scheme: str = "catbox"
    _API = "https://catbox.moe/user/api.php"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 60.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        filename = _make_filename()
        try:
            resp = await self._client.post(
                self._API,
                data={"reqtype": "fileupload", "userhash": ""},
                files={"fileToUpload": (filename, data, "application/json")},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"catbox upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"catbox HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = resp.text.strip()
        if not url.startswith(("https://", "http://")):
            raise MemoryAdapterError(f"catbox unexpected response: {url[:120]}")
        return make_ref("catbox", url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"catbox download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"catbox HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("catbox")


# ---------------------------------------------------------------------------
# 3. FileIoAdapter — file.io
# ---------------------------------------------------------------------------

class FileIoAdapter:
    """Ephemeral uploads to https://file.io.

    * No authentication.
    * Binary-safe via JSON envelope.
    * Files auto-delete on first download (single-use links).
    * Default expiry: 14 days.  Pass ``expires="1w"`` etc. to override.

    .. warning::
        ``get()`` is destructive — the remote copy is deleted after retrieval.
        Suitable for one-shot transfer / temp cache use-cases only.

    Ref format: ``ref:fileio:<key>``
    e.g.  ``ref:fileio:aB3dEf``
    """

    scheme: str = "fileio"
    _BASE = "https://file.io"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        expires: str = "14d",
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 60.0, fetch_hosts)
        self._expires = expires

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        filename = _make_filename()
        try:
            resp = await self._client.post(
                f"{self._BASE}/?expires={self._expires}",
                files={"file": (filename, data, "application/json")},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"file.io upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"file.io HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            body = resp.json()
        except Exception as exc:
            raise MemoryAdapterError(f"file.io invalid JSON response: {exc}") from exc
        if not body.get("success"):
            raise MemoryAdapterError(f"file.io error: {body}")
        key = body.get("key") or body.get("id") or ""
        if not key:
            raise MemoryAdapterError(f"file.io missing key in response: {body}")
        return make_ref("fileio", key)

    async def get(self, ref: str) -> Artifact:
        _, key = parse_ref(ref)
        url = f"{self._BASE}/{key}"
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"file.io download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"file.io HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, key = parse_ref(ref)
            resp = await self._client.head(f"{self._BASE}/{key}")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("fileio")


# ---------------------------------------------------------------------------
# 4. DpasteAdapter — dpaste.org
# ---------------------------------------------------------------------------

class DpasteAdapter:
    """Anonymous text pastes on https://dpaste.org.

    * No authentication.
    * Stores JSON envelope (supports binary via base64).
    * Practical size limit ~1 MB of raw text.
    * Configurable expiry (default: 2592000 s = 30 days; use ``"never"`` for permanent).

    .. note::
        As of 2025–2026 the public dpaste API has been **intermittently disabled**
        (HTTP 403/405). Prefer ``nullpointer`` or ``pasteee`` for new configs.

    Ref format: ``ref:dpaste:<slug>``
    e.g.  ``ref:dpaste:ABCDE``  →  https://dpaste.org/ABCDE/raw/
    """

    scheme: str = "dpaste"
    _API = "https://dpaste.org/api/"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        expires: str = "2592000",
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)
        self._expires = expires

    async def put(self, artifact: Artifact) -> str:
        text = _pack(artifact).decode("utf-8")
        try:
            resp = await self._client.post(
                self._API,
                data={
                    "content": text,
                    "format": "url",
                    "expires": self._expires,
                    "lexer": "_text",
                },
                headers={"User-Agent": "gemaxi-swarm/1.0"},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"dpaste upload error: {exc}") from exc
        if not resp.is_success:
            snippet = (resp.text or "")[:400]
            extra = ""
            low = snippet.lower()
            if resp.status_code in (403, 405) or "halt" in low or "red alert" in low:
                extra = (
                    " Public dpaste.org is often disabled; use "
                    "`--store pasters`, `catbox`, or paste.ee with PASTE_EE_API_KEY."
                )
            raise MemoryAdapterError(
                f"dpaste HTTP {resp.status_code}: {snippet[:200]}.{extra}"
            )
        url = resp.text.strip().strip('"')
        # URL looks like https://dpaste.org/SLUG/ — extract slug
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            raise MemoryAdapterError(f"dpaste unexpected URL: {url}")
        return make_ref("dpaste", slug)

    async def get(self, ref: str) -> Artifact:
        _, slug = parse_ref(ref)
        url = f"https://dpaste.org/{slug}/raw/"
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"dpaste download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"dpaste HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, slug = parse_ref(ref)
            resp = await self._client.head(f"https://dpaste.org/{slug}/raw/")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("dpaste")


# ---------------------------------------------------------------------------
# 5. IxioAdapter — ix.io
# ---------------------------------------------------------------------------

class IxioAdapter:
    """Anonymous text pastes on http://ix.io (IRC pastebin).

    * No authentication.
    * Stores JSON envelope (supports binary via base64).
    * Practical size limit ~64 KB.
    * Files may expire or be removed by the service without notice.

    Ref format: ``ref:ixio:<path>``
    e.g.  ``ref:ixio:4AbC``  →  http://ix.io/4AbC
    """

    scheme: str = "ixio"
    _BASE = "http://ix.io"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        text = _pack(artifact).decode("utf-8")
        try:
            resp = await self._client.post(
                self._BASE,
                data={"f:1": text},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"ix.io upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"ix.io HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = resp.text.strip()
        # URL like http://ix.io/XXXX — extract path
        path = url.rstrip("/").rsplit("/", 1)[-1]
        if not path:
            raise MemoryAdapterError(f"ix.io unexpected response: {url[:120]}")
        return make_ref("ixio", path)

    async def get(self, ref: str) -> Artifact:
        _, path = parse_ref(ref)
        url = f"{self._BASE}/{path}"
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"ix.io download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"ix.io HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, path = parse_ref(ref)
            resp = await self._client.head(f"{self._BASE}/{path}")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("ixio")


# ---------------------------------------------------------------------------
# 6. TelegraphAdapter — telegra.ph (anonymous wiki-like pages)
# ---------------------------------------------------------------------------

class TelegraphAdapter:
    """Anonymous publish on https://telegra.ph.

    * No authentication, no registration — uses ``createAccount`` (returns a
      throw-away short_name) then ``createPage`` to publish.
    * Stores JSON envelope as a single ``<pre>`` block (text-only).
    * Practical limit: ~64 KB per page.  Pages are publicly readable but the
      ref is opaque, providing storage by obscurity.

    Ref format: ``ref:telegraph:<path>`` (e.g. ``ref:telegraph:Gemaxi-12-31``)
    """

    scheme: str = "telegraph"
    _API = "https://api.telegra.ph"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)
        self._access_token: str | None = None

    async def _ensure_account(self) -> str:
        if self._access_token:
            return self._access_token
        try:
            resp = await self._client.get(
                f"{self._API}/createAccount",
                params={"short_name": "gemaxi", "author_name": "gemaxi-swarm"},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"telegraph createAccount error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(f"telegraph HTTP {resp.status_code}")
        body = resp.json()
        if not body.get("ok"):
            raise MemoryAdapterError(f"telegraph createAccount: {body}")
        token = body["result"]["access_token"]
        self._access_token = token
        return token

    async def put(self, artifact: Artifact) -> str:
        token = await self._ensure_account()
        text = _pack(artifact).decode("utf-8")
        content_nodes = json.dumps(
            [{"tag": "pre", "children": [text]}], ensure_ascii=False
        )
        try:
            resp = await self._client.post(
                f"{self._API}/createPage",
                data={
                    "access_token": token,
                    "title": "gemaxi",
                    "author_name": "gemaxi-swarm",
                    "content": content_nodes,
                    "return_content": "false",
                },
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"telegraph createPage error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(f"telegraph HTTP {resp.status_code}")
        body = resp.json()
        if not body.get("ok"):
            raise MemoryAdapterError(f"telegraph createPage: {body}")
        path = body["result"]["path"]
        return make_ref("telegraph", path)

    async def get(self, ref: str) -> Artifact:
        _, path = parse_ref(ref)
        try:
            resp = await self._client.get(
                f"{self._API}/getPage/{path}", params={"return_content": "true"}
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"telegraph getPage error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"telegraph HTTP {resp.status_code}")
        body = resp.json()
        if not body.get("ok"):
            raise RefNotFoundError(ref)
        nodes = body["result"].get("content") or []
        text = _telegraph_extract_text(nodes)
        return _unpack(text.encode("utf-8"))

    async def exists(self, ref: str) -> bool:
        try:
            _, path = parse_ref(ref)
            resp = await self._client.get(f"{self._API}/getPage/{path}")
            return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("telegraph")


def _telegraph_extract_text(nodes: Any) -> str:
    """Reassemble plain text from telegraph DOM-node tree."""
    parts: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, str):
            parts.append(n)
            return
        if isinstance(n, list):
            for child in n:
                walk(child)
            return
        if isinstance(n, dict):
            for child in n.get("children") or []:
                walk(child)

    walk(nodes)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 7. RentryAdapter — rentry.co (anonymous Markdown with edit code)
# ---------------------------------------------------------------------------

class RentryAdapter:
    """Anonymous Markdown pastes on https://rentry.co.

    * No authentication, no registration.
    * Permanent storage; deletion requires an edit-code returned at PUT time.
    * Stores JSON envelope as a fenced code-block (supports binary via base64).

    Ref format: ``ref:rentry:<url>`` (e.g. ``ref:rentry:abc123``).
    """

    scheme: str = "rentry"
    _API = "https://rentry.co/api/new"
    _BASE = "https://rentry.co"

    _CSRF_RE = re.compile(r"name=['\"]csrfmiddlewaretoken['\"]\s+value=['\"]([^'\"]+)['\"]")

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)
        self._edit_codes: dict[str, str] = {}

    async def _csrf(self) -> str:
        resp = await self._client.get(self._BASE)
        if not resp.is_success:
            raise MemoryAdapterError(f"rentry CSRF HTTP {resp.status_code}")
        m = self._CSRF_RE.search(resp.text)
        if not m:
            raise MemoryAdapterError("rentry CSRF token not found")
        cookie_val = resp.cookies.get("csrftoken", "")
        if cookie_val:
            self._client.cookies.set(
                "csrftoken", cookie_val, domain="rentry.co", path="/"
            )
        return m.group(1)

    async def put(self, artifact: Artifact) -> str:
        envelope = _pack(artifact).decode("utf-8")
        text = "```json\n" + envelope + "\n```\n"
        try:
            token = await self._csrf()
            resp = await self._client.post(
                self._API,
                data={
                    "csrfmiddlewaretoken": token,
                    "text": text,
                    "url": "",
                    "edit_code": "",
                },
                headers={"Referer": self._BASE},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"rentry upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(f"rentry HTTP {resp.status_code}")
        try:
            body = resp.json()
        except Exception as exc:
            raise MemoryAdapterError(f"rentry JSON parse: {exc}") from exc
        if body.get("status") != "200" and not body.get("url"):
            raise MemoryAdapterError(f"rentry error: {body}")
        url = body.get("url") or ""
        edit = body.get("edit_code") or ""
        if not url:
            raise MemoryAdapterError(f"rentry missing url in response: {body}")
        if edit:
            self._edit_codes[url] = edit
        return make_ref("rentry", url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(f"{self._BASE}/{url}/raw")
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"rentry get error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"rentry HTTP {resp.status_code}")
        body = resp.text
        # Strip the ```json … ``` fence
        body = body.strip()
        if body.startswith("```"):
            first_nl = body.find("\n")
            if first_nl >= 0:
                body = body[first_nl + 1 :]
            if body.endswith("```"):
                body = body[: -3]
            body = body.strip()
        return _unpack(body.encode("utf-8"))

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(f"{self._BASE}/{url}/raw")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("rentry")


# ---------------------------------------------------------------------------
# 8. PasteEEAdapter — paste.ee (API key required since ~2025)
# ---------------------------------------------------------------------------

class PasteEEAdapter:
    """Text pastes on https://paste.ee via ``POST /api/v1/pastes``.

    * Paste.ee requires an **Application key** (free): set
      ``memory_facade.cloud_paste.pasteee_api_key`` or env ``PASTE_EE_API_KEY``.
    * Sends ``X-Auth-Token: <key>`` on POST/GET per https://docs.paste.ee/
    * Stores JSON envelope (supports binary via base64).

    Ref format: ``ref:pasteee:<paste_id>``
    """

    scheme: str = "pasteee"
    _API = "https://api.paste.ee/v1/pastes"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        api_key: str | None = None,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)
        self._api_key = (api_key or "").strip() or None

    def _auth_headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {"X-Auth-Token": self._api_key}

    async def put(self, artifact: Artifact) -> str:
        text = _pack(artifact).decode("utf-8")
        try:
            resp = await self._client.post(
                self._API,
                json={
                    "description": "gemaxi",
                    "sections": [{"name": "gemaxi", "syntax": "json", "contents": text}],
                },
                headers=self._auth_headers(),
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"paste.ee upload error: {exc}") from exc
        if not resp.is_success:
            hint = ""
            if resp.status_code == 401 and not self._api_key:
                hint = (
                    " Get a free Application key at https://paste.ee/account/api "
                    "then set memory_facade.cloud_paste.pasteee_api_key or "
                    "environment variable PASTE_EE_API_KEY. Or use --store pasters."
                )
            raise MemoryAdapterError(
                f"paste.ee HTTP {resp.status_code}: {resp.text[:200]}{hint}"
            )
        try:
            body = resp.json()
        except Exception as exc:
            raise MemoryAdapterError(f"paste.ee invalid JSON: {exc}") from exc
        if body.get("success") is False:
            raise MemoryAdapterError(f"paste.ee error: {body}")
        pid = body.get("id")
        if not pid:
            raise MemoryAdapterError(f"paste.ee error: {body}")
        return make_ref("pasteee", str(pid))

    async def get(self, ref: str) -> Artifact:
        _, pid = parse_ref(ref)
        try:
            resp = await self._client.get(
                f"{self._API}/{pid}",
                headers=self._auth_headers(),
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"paste.ee get error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"paste.ee HTTP {resp.status_code}")
        body = resp.json()
        if not body.get("success"):
            raise RefNotFoundError(ref)
        sections = body.get("paste", {}).get("sections") or []
        if not sections:
            raise MemoryAdapterError("paste.ee: empty paste")
        content = sections[0].get("contents", "")
        return _unpack(content.encode("utf-8"))

    async def exists(self, ref: str) -> bool:
        try:
            _, pid = parse_ref(ref)
            resp = await self._client.get(
                f"{self._API}/{pid}",
                headers=self._auth_headers(),
            )
            return resp.status_code == 200 and resp.json().get("success", False)
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("pasteee")


# ---------------------------------------------------------------------------
# 9. TermbinAdapter — termbin.com (raw TCP pastebin, port 9999)
# ---------------------------------------------------------------------------

class TermbinAdapter:
    """Anonymous TCP pastebin at termbin.com:9999.

    * No HTTP, no auth — opens a raw TCP socket, writes payload, reads URL.
    * Permanent.  No envelope: stores raw bytes as base64+marker line so any
      content survives the text-only channel.
    * Practical size: a few hundred KB.
    """

    scheme: str = "termbin"
    _HOST = "termbin.com"
    _PORT = 9999

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._host = host or self._HOST
        self._port = port or self._PORT
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        import asyncio as _asyncio
        payload = _pack(artifact)
        try:
            reader, writer = await _asyncio.open_connection(self._host, self._port)
            writer.write(payload)
            with contextlib.suppress(NotImplementedError, OSError):
                writer.write_eof()
            await writer.drain()
            data = await reader.read(4096)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        except (TimeoutError, OSError) as exc:
            raise MemoryAdapterError(f"termbin TCP error: {exc}") from exc
        url = data.decode("utf-8", errors="replace").strip().strip("\x00")
        if not url.startswith(("http://", "https://")):
            raise MemoryAdapterError(f"termbin unexpected response: {url[:120]}")
        return make_ref("termbin", url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"termbin download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"termbin HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("termbin")


# ---------------------------------------------------------------------------
# 10. TmpFilesAdapter — tmpfiles.org (1-hour ephemeral)
# ---------------------------------------------------------------------------

class TmpFilesAdapter:
    """Anonymous binary uploads to https://tmpfiles.org (60 min retention)."""

    scheme: str = "tmpfiles"
    _API = "https://tmpfiles.org/api/v1/upload"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 60.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        try:
            resp = await self._client.post(
                self._API,
                files={"file": (_make_filename(), data, "application/json")},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"tmpfiles upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(f"tmpfiles HTTP {resp.status_code}")
        try:
            body = resp.json()
        except Exception as exc:
            raise MemoryAdapterError(f"tmpfiles bad JSON: {exc}") from exc
        if body.get("status") != "success":
            raise MemoryAdapterError(f"tmpfiles error: {body}")
        url = (body.get("data") or {}).get("url") or ""
        if not url:
            raise MemoryAdapterError(f"tmpfiles missing url: {body}")
        # tmpfiles returns a "viewer" URL; the raw url is /dl/<id>/<name>
        dl_url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        return make_ref("tmpfiles", dl_url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"tmpfiles download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"tmpfiles HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("tmpfiles")


# ---------------------------------------------------------------------------
# 11. TransferShAdapter — transfer.sh (PUT-style upload, 14d retention)
# ---------------------------------------------------------------------------

class TransferShAdapter:
    """Anonymous binary uploads via https://transfer.sh.

    * No auth — ``PUT /<filename>`` returns a direct download URL.
    * Default retention: 14 days.
    """

    scheme: str = "transfersh"
    _BASE = "https://transfer.sh"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 60.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        filename = _make_filename()
        try:
            resp = await self._client.put(f"{self._BASE}/{filename}", content=data)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"transfer.sh upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"transfer.sh HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = resp.text.strip()
        if not url.startswith(("http://", "https://")):
            raise MemoryAdapterError(f"transfer.sh unexpected response: {url[:120]}")
        return make_ref("transfersh", url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"transfer.sh download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"transfer.sh HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("transfersh")


# ---------------------------------------------------------------------------
# 12. SprungeAdapter — sprunge.us (simple text pastebin)
# ---------------------------------------------------------------------------

class SprungeAdapter:
    """Anonymous text pastes on http://sprunge.us (curl-friendly, no auth)."""

    scheme: str = "sprunge"
    _BASE = "http://sprunge.us"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        text = _pack(artifact).decode("utf-8")
        try:
            resp = await self._client.post(self._BASE, data={"sprunge": text})
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"sprunge upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"sprunge HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = resp.text.strip()
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            raise MemoryAdapterError(f"sprunge unexpected response: {url[:120]}")
        return make_ref("sprunge", slug)

    async def get(self, ref: str) -> Artifact:
        _, slug = parse_ref(ref)
        try:
            resp = await self._client.get(f"{self._BASE}/{slug}")
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"sprunge download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"sprunge HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, slug = parse_ref(ref)
            resp = await self._client.head(f"{self._BASE}/{slug}")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("sprunge")


# ---------------------------------------------------------------------------
# 13. PasteRsAdapter — paste.rs (POST raw body, no auth)
# ---------------------------------------------------------------------------

class PasteRsAdapter:
    """Anonymous text pastes on https://paste.rs (no JS, no auth).

    POST raw body → response is the full URL.
    """

    scheme: str = "pasters"
    _BASE = "https://paste.rs"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        try:
            resp = await self._client.post(self._BASE, content=data)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"paste.rs upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"paste.rs HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = resp.text.strip()
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            raise MemoryAdapterError(f"paste.rs unexpected response: {url[:120]}")
        return make_ref("pasters", slug)

    async def get(self, ref: str) -> Artifact:
        _, slug = parse_ref(ref)
        try:
            resp = await self._client.get(f"{self._BASE}/{slug}")
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"paste.rs download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"paste.rs HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, slug = parse_ref(ref)
            resp = await self._client.head(f"{self._BASE}/{slug}")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("pasters")


# ---------------------------------------------------------------------------
# 14. HastebinAdapter — hastebin.com (~400 KB pastes)
# ---------------------------------------------------------------------------

class HastebinAdapter:
    """Anonymous text pastes on https://hastebin.com (haste-server)."""

    scheme: str = "hastebin"
    _BASE = "https://hastebin.com"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        base: str | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 30.0, fetch_hosts)
        if base:
            self._BASE = base.rstrip("/")

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        try:
            resp = await self._client.post(f"{self._BASE}/documents", content=data)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"hastebin upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"hastebin HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            body = resp.json()
        except Exception as exc:
            raise MemoryAdapterError(f"hastebin bad JSON: {exc}") from exc
        key = body.get("key")
        if not key:
            raise MemoryAdapterError(f"hastebin missing key: {body}")
        return make_ref("hastebin", key)

    async def get(self, ref: str) -> Artifact:
        _, key = parse_ref(ref)
        try:
            resp = await self._client.get(f"{self._BASE}/raw/{key}")
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"hastebin download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"hastebin HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, key = parse_ref(ref)
            resp = await self._client.head(f"{self._BASE}/raw/{key}")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("hastebin")


# ---------------------------------------------------------------------------
# 15. PixelDrainAdapter — pixeldrain.com (binary, 20 GB, anonymous)
# ---------------------------------------------------------------------------

class PixelDrainAdapter:
    """Anonymous uploads to https://pixeldrain.com.

    * No authentication.
    * Binary-safe via JSON envelope.
    * Up to 20 GB per file, files persist as long as they receive views.
    * Public API documented at https://pixeldrain.com/api

    Ref format: ``ref:pixeldrain:<id>``
    """

    scheme: str = "pixeldrain"
    _API = "https://pixeldrain.com/api/file"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        base: str | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 120.0, fetch_hosts)
        if base:
            self._API = base.rstrip("/") + "/api/file"

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        filename = _make_filename()
        try:
            resp = await self._client.post(
                self._API,
                files={"file": (filename, data, "application/json")},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"pixeldrain upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"pixeldrain HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            body = resp.json()
        except Exception as exc:
            raise MemoryAdapterError(f"pixeldrain bad JSON: {exc}") from exc
        file_id = body.get("id")
        if not file_id:
            raise MemoryAdapterError(f"pixeldrain missing id: {body}")
        return make_ref("pixeldrain", file_id)

    async def get(self, ref: str) -> Artifact:
        _, file_id = parse_ref(ref)
        url = f"{self._API}/{file_id}"
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"pixeldrain download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"pixeldrain HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, file_id = parse_ref(ref)
            resp = await self._client.head(f"{self._API}/{file_id}")
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("pixeldrain")


# ---------------------------------------------------------------------------
# 16. FilebinAdapter — filebin.net (binary, bin-style, 6-day default)
# ---------------------------------------------------------------------------

class FilebinAdapter:
    """Anonymous uploads to https://filebin.net.

    * No authentication.
    * Binary-safe via JSON envelope.
    * Bins auto-created on first PUT; default lifetime 6 days from last access.
    * Each adapter instance shares one bin name — pass ``bin`` to override.

    Ref format: ``ref:filebin:<bin>/<filename>``
    """

    scheme: str = "filebin"
    _BASE = "https://filebin.net"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        bin: str | None = None,
        base: str | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 120.0, fetch_hosts)
        if base:
            self._BASE = base.rstrip("/")
        self._bin = bin or f"gemaxi-{uuid.uuid4().hex[:12]}"

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        filename = _make_filename()
        url = f"{self._BASE}/{self._bin}/{filename}"
        try:
            resp = await self._client.post(
                url,
                content=data,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"filebin upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"filebin HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return make_ref("filebin", f"{self._bin}/{filename}")

    async def get(self, ref: str) -> Artifact:
        _, path = parse_ref(ref)
        url = f"{self._BASE}/{path}"
        try:
            resp = await self._client.get(url, follow_redirects=True)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"filebin download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"filebin HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, path = parse_ref(ref)
            resp = await self._client.head(
                f"{self._BASE}/{path}", follow_redirects=True
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        try:
            _, path = parse_ref(ref)
            resp = await self._client.delete(f"{self._BASE}/{path}")
            return resp.is_success
        except Exception:
            return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return Capabilities(
            schemes=frozenset({"filebin"}),
            supports_search=False,
            supports_delete=True,
            supports_promote=False,
        )


# ---------------------------------------------------------------------------
# 17. LitterboxAdapter — litterbox.catbox.moe (temp binary, 1h–72h)
# ---------------------------------------------------------------------------

class LitterboxAdapter:
    """Anonymous temp uploads to https://litterbox.catbox.moe.

    * No authentication.
    * Binary-safe via JSON envelope.
    * Files self-destruct after 1h / 12h / 24h / 72h (passed via ``time``).
    * Useful for short-lived exchanges (e.g. one-shot dropbox handoff).

    Ref format: ``ref:litterbox:<full_url>``
    """

    scheme: str = "litterbox"
    _API = "https://litterbox.catbox.moe/resources/internals/api.php"
    _VALID_TIMES = {"1h", "12h", "24h", "72h"}

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        time: str = "72h",
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        if time not in self._VALID_TIMES:
            raise ValueError(f"litterbox time must be one of {self._VALID_TIMES}")
        self._client = _wrap_cloud_client(client, 120.0, fetch_hosts)
        self._time = time

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        filename = _make_filename()
        try:
            resp = await self._client.post(
                self._API,
                data={"reqtype": "fileupload", "time": self._time},
                files={"fileToUpload": (filename, data, "application/json")},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"litterbox upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"litterbox HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = resp.text.strip()
        if not url.startswith(("https://", "http://")):
            raise MemoryAdapterError(f"litterbox unexpected response: {url[:120]}")
        return make_ref("litterbox", url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"litterbox download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"litterbox HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("litterbox")


# ---------------------------------------------------------------------------
# 18. BashuploadAdapter — bashupload.com (binary, 3 days)
# ---------------------------------------------------------------------------

class BashuploadAdapter:
    """Anonymous uploads to https://bashupload.com.

    * No authentication.
    * Binary-safe via JSON envelope.
    * Files persist for 3 days, max 50 GB/month per IP.
    * Server returns a plain-text body with the download URL on the
      ``wget`` line; parser extracts the first ``http(s)://...`` token.

    Ref format: ``ref:bashupload:<full_url>``
    """

    scheme: str = "bashupload"
    _BASE = "https://bashupload.com"
    _URL_RE = re.compile(r"https?://\S+")

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        base: str | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 120.0, fetch_hosts)
        if base:
            self._BASE = base.rstrip("/")

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        filename = _make_filename()
        url = f"{self._BASE}/{filename}"
        try:
            resp = await self._client.put(url, content=data)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"bashupload upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"bashupload HTTP {resp.status_code}: {resp.text[:200]}"
            )
        match = self._URL_RE.search(resp.text)
        if not match:
            raise MemoryAdapterError(
                f"bashupload could not parse download URL from: {resp.text[:200]}"
            )
        return make_ref("bashupload", match.group(0).rstrip(".,;"))

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url, follow_redirects=True)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"bashupload download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"bashupload HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url, follow_redirects=True)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("bashupload")


# ---------------------------------------------------------------------------
# 19. ClbinAdapter — clbin.com (text, ix.io alternative)
# ---------------------------------------------------------------------------

class ClbinAdapter:
    """Anonymous text pastes on https://clbin.com.

    * No authentication.
    * Text envelope; binary content auto-wrapped via JSON+base64.
    * Permanent storage, no expiry.

    Ref format: ``ref:clbin:<full_url>``
    """

    scheme: str = "clbin"
    _BASE = "https://clbin.com"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        base: str | None = None,
        *,
        fetch_hosts: frozenset[str] | None = None,
    ) -> None:
        self._client = _wrap_cloud_client(client, 60.0, fetch_hosts)
        if base:
            self._BASE = base.rstrip("/")

    async def put(self, artifact: Artifact) -> str:
        data = _pack(artifact)
        try:
            resp = await self._client.post(
                self._BASE,
                files={"clbin": ("envelope.json", data, "application/json")},
            )
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"clbin upload error: {exc}") from exc
        if not resp.is_success:
            raise MemoryAdapterError(
                f"clbin HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = resp.text.strip()
        if not url.startswith(("https://", "http://")):
            raise MemoryAdapterError(f"clbin unexpected response: {url[:120]}")
        return make_ref("clbin", url)

    async def get(self, ref: str) -> Artifact:
        _, url = parse_ref(ref)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            raise MemoryAdapterError(f"clbin download error: {exc}") from exc
        if resp.status_code == 404:
            raise RefNotFoundError(ref)
        if not resp.is_success:
            raise MemoryAdapterError(f"clbin HTTP {resp.status_code}")
        return _unpack(resp.content)

    async def exists(self, ref: str) -> bool:
        try:
            _, url = parse_ref(ref)
            resp = await self._client.head(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return _no_caps("clbin")
