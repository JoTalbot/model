"""Host allowlist and IP-range checks for outbound HTTP from memory adapters.

Mitigates SSRF when ``ref:`` values carry full URLs (e.g. ``nullpointer``,
``catbox``) or when paste services return redirect targets. Redirect chains
are not re-validated per hop (httpx); first-hop URL is always checked.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from swarm.memory.types import MemoryAdapterError

# Hostnames used by built-in paste adapters (lowercase, no ports).
BUILTIN_FETCH_HOSTS: frozenset[str] = frozenset(
    {
        "0x0.st",
        "api.paste.ee",
        "api.telegra.ph",
        "bashupload.com",
        "catbox.moe",
        "clbin.com",
        "dpaste.org",
        "file.io",
        "filebin.net",
        "files.catbox.moe",
        "hastebin.com",
        "ix.io",
        "litter.catbox.moe",
        "litterbox.catbox.moe",
        "paste.ee",
        "paste.rs",
        "pixeldrain.com",
        "rentry.co",
        "sprunge.us",
        "telegra.ph",
        "termbin.com",
        "tmpfiles.org",
        "transfer.sh",
    }
)


def resolve_fetch_hosts(fetch_hosts: frozenset[str] | None) -> frozenset[str]:
    """Return effective allowlist (``None`` → built-in defaults)."""
    return BUILTIN_FETCH_HOSTS if fetch_hosts is None else fetch_hosts


def http_link_allowlist_from_memory_facade(mf: dict[str, Any]) -> frozenset[str] | None:
    """Return host allowlist for ``ref:http`` / ``ref:https`` when enabled.

    ``memory_facade.http_links.enabled: true`` requires a non-empty
    ``http_links.allowlist`` of hostnames (SSRF mitigation for arbitrary URLs).
    """
    hl = mf.get("http_links") or {}
    if not hl.get("enabled"):
        return None
    raw = hl.get("allowlist") or []
    hosts = frozenset(str(x).strip().lower() for x in raw if str(x).strip())
    if not hosts:
        raise MemoryAdapterError(
            "memory_facade.http_links.enabled is true but http_links.allowlist is empty; "
            "set explicit hostnames (e.g. example.com) for outbound link fetches."
        )
    return hosts


def resolve_allowed_hosts_from_cloud_paste_cfg(cloud_cfg: dict[str, Any]) -> frozenset[str]:
    """Build host allowlist from ``memory_facade.cloud_paste`` YAML dict.

    * ``http_fetch_allowlist`` — if present (including empty list), **replaces**
      the built-in set entirely. Use ``http_fetch_allowlist_extra`` to extend
      defaults instead.
    * ``http_fetch_allowlist_extra`` — hostnames merged into the active base set.
    """
    if "http_fetch_allowlist" in cloud_cfg:
        raw = cloud_cfg.get("http_fetch_allowlist")
        if raw is None:
            base = BUILTIN_FETCH_HOSTS
        else:
            base = frozenset(
                str(x).strip().lower()
                for x in (raw or [])
                if str(x).strip()
            )
    else:
        base = BUILTIN_FETCH_HOSTS
    extra = cloud_cfg.get("http_fetch_allowlist_extra") or []
    extra_hosts = frozenset(
        str(x).strip().lower() for x in extra if str(x).strip()
    )
    return base | extra_hosts


def assert_http_fetch_allowed(url: str, allowed_hosts: frozenset[str]) -> None:
    """Raise ``MemoryAdapterError`` if ``url`` must not be fetched."""
    try:
        parsed = urlparse(str(url))
    except Exception as exc:
        raise MemoryAdapterError(f"HTTP fetch blocked: invalid URL {url!r}") from exc
    if parsed.scheme not in ("http", "https"):
        raise MemoryAdapterError(
            f"HTTP fetch blocked: scheme {parsed.scheme!r} not allowed for {url!r}"
        )
    host = parsed.hostname
    if not host:
        raise MemoryAdapterError(f"HTTP fetch blocked: missing host in {url!r}")
    host_l = host.lower()
    try:
        ip = ipaddress.ip_address(host_l)
    except ValueError:
        ip = None
    if ip is not None:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise MemoryAdapterError(
                f"HTTP fetch blocked: disallowed address {host_l!r} in {url!r}"
            )
        raise MemoryAdapterError(
            f"HTTP fetch blocked: literal IP host {host_l!r} in {url!r} "
            "(paste adapters require hostnames on the allowlist)"
        )
    if host_l not in allowed_hosts:
        raise MemoryAdapterError(
            f"HTTP fetch blocked: host {host_l!r} not in allowlist for {url!r}"
        )


class GuardedHttpxClient:
    """Delegates to ``httpx.AsyncClient`` while enforcing ``assert_http_fetch_allowed``."""

    __slots__ = ("_allowed", "_inner")

    def __init__(self, inner: httpx.AsyncClient, allowed_hosts: frozenset[str]) -> None:
        self._inner = inner
        self._allowed = allowed_hosts

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return self._allowed

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def get(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        assert_http_fetch_allowed(str(url), self._allowed)
        return await self._inner.get(url, *args, **kwargs)

    async def post(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        assert_http_fetch_allowed(str(url), self._allowed)
        return await self._inner.post(url, *args, **kwargs)

    async def put(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        assert_http_fetch_allowed(str(url), self._allowed)
        return await self._inner.put(url, *args, **kwargs)

    async def patch(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        assert_http_fetch_allowed(str(url), self._allowed)
        return await self._inner.patch(url, *args, **kwargs)

    async def delete(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        assert_http_fetch_allowed(str(url), self._allowed)
        return await self._inner.delete(url, *args, **kwargs)

    async def head(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        assert_http_fetch_allowed(str(url), self._allowed)
        return await self._inner.head(url, *args, **kwargs)

    async def request(self, method: str, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        assert_http_fetch_allowed(str(url), self._allowed)
        return await self._inner.request(method, url, *args, **kwargs)


def guard_http_client(
    client: httpx.AsyncClient,
    fetch_hosts: frozenset[str] | None,
) -> httpx.AsyncClient:
    """Wrap ``client`` with policy checks, or return unchanged if already guarded."""
    hosts = resolve_fetch_hosts(fetch_hosts)
    if isinstance(client, GuardedHttpxClient) and client.allowed_hosts == hosts:
        return client
    return GuardedHttpxClient(client, hosts)
