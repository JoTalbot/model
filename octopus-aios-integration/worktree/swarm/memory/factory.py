from __future__ import annotations

import os
from pathlib import Path

import httpx

from swarm.memory.adapters.http_link import LinkAdapter
from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.adapters.obsidian import ObsidianVaultAdapter
from swarm.memory.adapters.paste_cloud import (
    BashuploadAdapter,
    CatboxAdapter,
    ClbinAdapter,
    DpasteAdapter,
    FilebinAdapter,
    FileIoAdapter,
    HastebinAdapter,
    IxioAdapter,
    LitterboxAdapter,
    NullpointerAdapter,
    PasteEEAdapter,
    PasteRsAdapter,
    PixelDrainAdapter,
    RentryAdapter,
    SprungeAdapter,
    TelegraphAdapter,
    TermbinAdapter,
    TmpFilesAdapter,
    TransferShAdapter,
)
from swarm.memory.adapters.swarm_store import DhtErasureAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.http_fetch_guard import (
    guard_http_client,
    http_link_allowlist_from_memory_facade,
    resolve_allowed_hosts_from_cloud_paste_cfg,
)
from swarm.memory.types import MemoryAdapterError
from swarm.network.outbound_http import httpx_proxy_kwargs

# Map config key → adapter class.  TermbinAdapter uses TCP for ``put`` and the
# shared HTTP client for ``get`` / ``exists``.
_CLOUD_ADAPTERS: dict[str, type] = {
    "nullpointer": NullpointerAdapter,
    "catbox": CatboxAdapter,
    "fileio": FileIoAdapter,
    "dpaste": DpasteAdapter,
    "ixio": IxioAdapter,
    "telegraph": TelegraphAdapter,
    "rentry": RentryAdapter,
    "pasteee": PasteEEAdapter,
    "tmpfiles": TmpFilesAdapter,
    "transfersh": TransferShAdapter,
    "sprunge": SprungeAdapter,
    "pasters": PasteRsAdapter,
    "hastebin": HastebinAdapter,
    "pixeldrain": PixelDrainAdapter,
    "filebin": FilebinAdapter,
    "litterbox": LitterboxAdapter,
    "bashupload": BashuploadAdapter,
    "clbin": ClbinAdapter,
}

# Adapters that do not accept an HTTP client (special constructor).
_NON_HTTP_CLOUD: dict[str, type] = {
    "termbin": TermbinAdapter,
}


def _cloud_adapter_init_kwargs(key: str, cloud_cfg: dict) -> dict[str, object]:
    """Per-adapter constructor kwargs from ``memory_facade.cloud_paste``."""
    if key == "pasteee":
        ak = cloud_cfg.get("pasteee_api_key")
        if isinstance(ak, str) and ak.strip():
            return {"api_key": ak.strip()}
        envk = (os.environ.get("PASTE_EE_API_KEY") or "").strip()
        if envk:
            return {"api_key": envk}
    return {}


def extend_memory_facade_network_adapters(
    cfg: dict, adapters: dict[str, object]
) -> None:
    """Register ``cloud_paste`` and optional ``http_links`` adapters (mutates ``adapters``).

    Used by ``build_memory_port`` and by CLI helpers that build a composite
    without a live ``DistributedMemory`` (local scratch + anonymous pastebins).
    """
    mf = cfg.get("memory_facade") or {}
    try:
        px_kw = httpx_proxy_kwargs(cfg)
    except ValueError as exc:
        raise MemoryAdapterError(str(exc)) from exc

    cloud_cfg = mf.get("cloud_paste") or {}
    if cloud_cfg:
        fetch_hosts = resolve_allowed_hosts_from_cloud_paste_cfg(cloud_cfg)
        shared_client = httpx.AsyncClient(timeout=60.0, **px_kw)
        for key, cls in _CLOUD_ADAPTERS.items():
            if cloud_cfg.get(key):
                extra = _cloud_adapter_init_kwargs(key, cloud_cfg)
                adapters[key] = cls(
                    client=shared_client,
                    fetch_hosts=fetch_hosts,
                    **extra,
                )
        for key, cls in _NON_HTTP_CLOUD.items():
            if cloud_cfg.get(key):
                adapters[key] = cls(client=shared_client, fetch_hosts=fetch_hosts)

    link_hosts = http_link_allowlist_from_memory_facade(mf)
    if link_hosts is not None:
        link_client = httpx.AsyncClient(timeout=30.0, **px_kw)
        guarded = guard_http_client(link_client, link_hosts)
        adapters["https"] = LinkAdapter(guarded, scheme="https")
        adapters["http"] = LinkAdapter(guarded, scheme="http")


def build_memory_port(cfg: dict, distributed_memory) -> CompositeMemoryPort | None:
    """Build a `CompositeMemoryPort` from YAML-style ``cfg``.

    Expects ``cfg["memory_facade"]`` (or missing / empty dict for disabled).
    When enabled, ``distributed_memory`` must be a live ``DistributedMemory`` instance.

    Optional ``memory_facade.cloud_paste`` sub-section activates anonymous
    online storage adapters (most need no keys; **paste.ee** needs an
    Application key: ``pasteee_api_key`` or env ``PASTE_EE_API_KEY``)::

        memory_facade:
          enabled: true
          cloud_paste:
            pasters: true       # https://paste.rs — text, no API key
            pasteee: true       # https://paste.ee — requires pasteee_api_key
            pasteee_api_key: "your-key-from-https://paste.ee/account/api"
            nullpointer: false  # https://0x0.st — binary; uploads often disabled
            catbox: true        # https://catbox.moe — binary, 200 MB, permanent
            fileio: true        # https://file.io — binary, auto-deletes on download
            dpaste: false       # https://dpaste.org — text; public API often offline
            ixio: true          # https://ix.io — text, 64 KB
            # http_fetch_allowlist: []       # replace built-in host allowlist
            # http_fetch_allowlist_extra: [] # merge extra hostnames into allowlist

    Optional ``memory_facade.http_links`` registers read-only ``ref:https:`` /
    ``ref:http:`` adapters; ``allowlist`` must list every allowed hostname (SSRF)::

        memory_facade:
          enabled: true
          http_links:
            enabled: true
            allowlist: ["example.com", "cdn.example.org"]

    Use ``artifact.attrs["store"] = "<scheme>"`` to route a ``put()`` to the
    desired cloud adapter.

    Root ``network.outbound_proxy`` (optional) is passed to all ``httpx``
    clients built here (cloud paste + http links) for Tor/corporate egress.
    """
    mf = cfg.get("memory_facade") or {}
    if not mf.get("enabled", False):
        return None
    if distributed_memory is None:
        raise MemoryAdapterError(
            "memory_facade.enabled is true but distributed_memory is None; "
            "the swarm adapter requires a running DistributedMemory instance"
        )

    scratch_root = mf.get("scratch_root", ".swarm_scratch")

    # PostgreSQL backend: если scratch_root начинается с postgres:// или postgresql://
    owner_id = getattr(distributed_memory, "_node_id", None) or "unknown"
    if str(scratch_root).startswith(("postgres://", "postgresql://")):
        from swarm.memory.adapters.postgres_adapter import PostgreSQLAdapter
        local = PostgreSQLAdapter(str(scratch_root))
        import logging as _log
        _log.getLogger(__name__).info("Using PostgreSQL backend: %s", str(scratch_root).split("@")[-1])
    else:
        root = Path(scratch_root).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        local = LocalScratchAdapter(root)
    swarm = DhtErasureAdapter(
        distributed_memory,
        owner_id=owner_id,
        default_block_type=mf.get("default_block_type", "knowledge"),
    )
    adapters: dict[str, object] = {"file": local, "swarm": swarm}

    obsidian_cfg = mf.get("obsidian") or {}
    if obsidian_cfg.get("enabled"):
        vault_root = obsidian_cfg.get("vault_root") or str(root / "wiki")
        adapters["obsidian"] = ObsidianVaultAdapter(vault_root)

    extend_memory_facade_network_adapters(cfg, adapters)

    return CompositeMemoryPort(adapters)
