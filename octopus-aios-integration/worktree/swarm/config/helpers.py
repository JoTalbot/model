"""Shared config parsing helpers used by both CLI and runtime.

Previously duplicated between ``swarm/cli.py`` and ``swarm/runtime.py``.
"""

from __future__ import annotations

from swarm.llm.key_pool import APIKey, KeyPool


def yaml_bootstrap_addr(cfg: dict) -> tuple[str, int] | None:
    """Parse the first ``node.bootstrap`` entry from config dict.

    Returns ``(host, port)`` or ``None``.
    """
    node = cfg.get("node") or {}
    b = node.get("bootstrap", [])
    if isinstance(b, str) and b.strip():
        b = [b.strip()]
    if not b:
        return None
    first = b[0]
    if isinstance(first, str) and ":" in first:
        host, port_s = first.rsplit(":", 1)
        return host.strip(), int(port_s.strip())
    return None


def llm_local_router_kwargs(llm_cfg: dict) -> dict:
    """Build kwargs for local OpenAI-compatible server.

    Returns empty dict when local mode is disabled.
    """
    loc = llm_cfg.get("local") or {}
    if not loc.get("enabled"):
        return {}
    base = (loc.get("base_url") or "").strip()
    models = loc.get("models") or []
    if not base or not models:
        return {}
    out: dict = {
        "local_base_url": base,
        "local_models": list(models),
        "prefer_local": bool(loc.get("prefer_local", False)),
    }
    ak = loc.get("api_key")
    if isinstance(ak, str) and ak.strip():
        out["local_api_key"] = ak.strip()
    return out


def llm_key_pool(llm_cfg: dict, local_kw: dict) -> KeyPool:
    """Create a :class:`KeyPool` from config, raising if none available."""
    keys = [APIKey(key=k) for k in llm_cfg.get("keys") or []]
    if keys:
        return KeyPool(keys=keys)
    if local_kw:
        return KeyPool(keys=[APIKey(key="local-placeholder")])
    raise ValueError(
        "Add OpenRouter keys to config.yaml (llm.keys), or enable llm.local "
        "with base_url and models for offline mode."
    )


def parse_repair_seeds(raw: object) -> list[tuple[str, int]]:
    """Parse ``memory.repair_seeds`` entries like ``host:kad_port``."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, str) or ":" not in item:
            continue
        host, _, sport = item.rpartition(":")
        try:
            out.append((host.strip(), int(sport.strip())))
        except ValueError:
            continue
    return out


__all__ = [
    "llm_key_pool",
    "llm_local_router_kwargs",
    "parse_repair_seeds",
    "yaml_bootstrap_addr",
]
