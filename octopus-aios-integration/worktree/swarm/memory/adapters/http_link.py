from __future__ import annotations

from urllib.parse import unquote

import httpx

from swarm.memory.ref_parse import RefFormatError, parse_ref
from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    RefMeta,
    RefNotFoundError,
)


def _absolute_url(scheme: str, decoded: str) -> str:
    """Ensure a URL httpx can request (absolute with http(s) scheme)."""
    if decoded.startswith(("http://", "https://")):
        return decoded
    return f"{scheme}://{decoded}"


def _mime_from_response(response: httpx.Response) -> str:
    raw = response.headers.get("content-type")
    if not raw:
        return "application/octet-stream"
    return raw.split(";", 1)[0].strip() or "application/octet-stream"


class LinkAdapter:
    """Read-only adapter: `ref:http:...` / `ref:https:...` with URL-encoded opaque."""

    def __init__(self, client: httpx.AsyncClient, scheme: str = "https") -> None:
        if scheme not in ("http", "https"):
            raise ValueError("scheme must be 'http' or 'https'")
        self._scheme = scheme
        self._client = client

    @property
    def scheme(self) -> str:
        return self._scheme

    async def put(self, artifact: Artifact) -> str:
        raise MemoryAdapterError("LinkAdapter is read-only")

    async def get(self, ref: str) -> Artifact:
        scheme, opaque = parse_ref(ref)
        if scheme != self._scheme:
            raise RefNotFoundError(ref)
        raw = unquote(opaque)
        if not raw.strip():
            raise RefNotFoundError(ref)
        url = _absolute_url(self._scheme, raw)
        response = await self._client.get(url)
        if response.status_code == 404:
            raise RefNotFoundError(ref)
        if not response.is_success:
            raise MemoryAdapterError(
                f"HTTP {response.status_code} fetching {url!r}"
            )
        return Artifact(
            content=response.content,
            mime=_mime_from_response(response),
            tags=["trust:external"],
            provenance={"url": url},
        )

    async def exists(self, ref: str) -> bool:
        try:
            scheme, opaque = parse_ref(ref)
        except RefFormatError:
            return False
        if scheme != self._scheme:
            return False
        return bool(unquote(opaque).strip())

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return []

    def capabilities(self) -> Capabilities:
        return Capabilities(
            schemes=frozenset({self._scheme}),
            supports_search=False,
            supports_delete=False,
            supports_promote=False,
        )
