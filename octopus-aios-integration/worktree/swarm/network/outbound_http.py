"""Optional outbound HTTP/HTTPS/SOCKS proxy for ``httpx`` (Tor sidecar, corporate).

Configured via ``network.outbound_proxy`` in the root YAML (see ``config.yaml``).
SOCKS requires the ``socksio`` extra (``httpx[socks]`` in requirements).
"""

from __future__ import annotations

from typing import Any

_ALLOWED_PREFIXES = (
    "http://",
    "https://",
    "socks5://",
    "socks5h://",
    "socks4://",
)


def outbound_http_proxy_url(cfg: dict[str, Any]) -> str | None:
    """Return trimmed proxy URL or ``None`` if unset/blank.

    Raises ``ValueError`` if set but the scheme is not allowed.
    """
    net = cfg.get("network") or {}
    raw = net.get("outbound_proxy")
    if raw is None:
        return None
    url = str(raw).strip()
    if not url:
        return None
    lower = url.lower()
    if not any(lower.startswith(p) for p in _ALLOWED_PREFIXES):
        raise ValueError(
            "network.outbound_proxy must be an http(s) or socks URL "
            f"(one of prefixes {_ALLOWED_PREFIXES}), got {url!r}"
        )
    return url


def httpx_proxy_kwargs(cfg: dict[str, Any]) -> dict[str, str]:
    """Keyword args for ``httpx.AsyncClient(..., **returned)`` (empty if no proxy)."""
    p = outbound_http_proxy_url(cfg)
    return {"proxy": p} if p else {}
