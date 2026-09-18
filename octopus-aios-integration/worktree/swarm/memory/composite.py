from __future__ import annotations

import asyncio
import time
from typing import Any

from swarm.memory.port import MemoryMetrics
from swarm.memory.ref_parse import parse_ref
from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    PromotionError,
    RefMeta,
)


def _artifact_size(artifact: Artifact) -> int:
    content = artifact.content
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    return len(content)


class CompositeMemoryPort:
    """Facade routing `ref:<scheme>:<opaque>` to registered adapters.

    Default put route is ``file``; ``artifact.attrs["store"] == "swarm"`` opts
    into the swarm adapter. ``promote`` migrates a file-scheme ref into swarm.

    Parameters
    ----------
    bus:
        Optional :class:`EventBus` — when supplied, the port emits
        :class:`MemoryPut`, :class:`MemoryGetOk`, :class:`MemoryGetFailed`
        events for every operation.
    """

    def __init__(self, adapters: dict[str, Any], *, bus=None) -> None:
        self._adapters: dict[str, Any] = dict(adapters)
        self._metrics = MemoryMetrics()
        self._bus = bus

    @property
    def metrics(self) -> MemoryMetrics:
        return self._metrics

    def _adapter_for(self, scheme: str) -> Any:
        adapter = self._adapters.get(scheme)
        if adapter is None:
            raise MemoryAdapterError(
                f"no adapter registered for scheme {scheme!r}"
            )
        return adapter

    async def _emit(self, event: object) -> None:
        if self._bus is not None:
            await self._bus.publish(event)

    async def put(self, artifact: Artifact) -> str:
        attrs = artifact.attrs or {}
        requested = attrs.get("store")
        scheme = requested if requested else "file"
        adapter = self._adapter_for(scheme)
        size = _artifact_size(artifact)
        t0 = time.perf_counter()
        try:
            ref = await adapter.put(artifact)
        except Exception as exc:
            self._metrics.record_error(scheme, repr(exc))
            raise
        self._metrics.record_latency(scheme, "put", time.perf_counter() - t0)
        self._metrics.record_put(scheme)
        self._metrics.record_bytes_out(scheme, size)

        from swarm.events.events import MemoryPut as MemoryPutEvent
        await self._emit(MemoryPutEvent(scheme=scheme, ref=ref, size_bytes=size))

        return ref

    async def get(self, ref: str) -> Artifact:
        scheme, _ = parse_ref(ref)
        adapter = self._adapters.get(scheme)
        if adapter is None:
            self._metrics.record_get(scheme, ok=False)
            self._metrics.record_error(
                scheme, f"no adapter registered for scheme {scheme!r}"
            )
            from swarm.events.events import MemoryGetFailed
            await self._emit(MemoryGetFailed(
                scheme=scheme, ref=ref,
                error=f"no adapter registered for scheme {scheme!r}",
            ))
            raise MemoryAdapterError(
                f"no adapter registered for scheme {scheme!r}"
            )
        t0 = time.perf_counter()
        try:
            artifact = await adapter.get(ref)
        except Exception as exc:
            self._metrics.record_latency(scheme, "get", time.perf_counter() - t0)
            self._metrics.record_get(scheme, ok=False)
            self._metrics.record_error(scheme, repr(exc))
            from swarm.events.events import MemoryGetFailed
            await self._emit(MemoryGetFailed(scheme=scheme, ref=ref, error=repr(exc)))
            raise
        self._metrics.record_latency(scheme, "get", time.perf_counter() - t0)
        self._metrics.record_get(scheme, ok=True)
        size = _artifact_size(artifact)
        self._metrics.record_bytes_in(scheme, size)

        from swarm.events.events import MemoryGetOk
        await self._emit(MemoryGetOk(scheme=scheme, ref=ref, size_bytes=size))

        return artifact

    async def exists(self, ref: str) -> bool:
        scheme, _ = parse_ref(ref)
        adapter = self._adapters.get(scheme)
        if adapter is None:
            return False
        return await adapter.exists(ref)

    async def delete(self, ref: str) -> bool:
        scheme, _ = parse_ref(ref)
        adapter = self._adapter_for(scheme)
        return await adapter.delete(ref)

    async def search(
        self, tags: list[str], owner: str | None = None
    ) -> list[RefMeta]:
        searchable = [
            adapter
            for adapter in self._adapters.values()
            if adapter.capabilities().supports_search
        ]
        if not searchable:
            return []
        results = await asyncio.gather(
            *(adapter.search(tags, owner) for adapter in searchable)
        )
        seen: set[str] = set()
        merged: list[RefMeta] = []
        for batch in results:
            for meta in batch:
                if meta.ref in seen:
                    continue
                seen.add(meta.ref)
                merged.append(meta)
        return merged

    async def promote(self, ref: str) -> str:
        scheme, _ = parse_ref(ref)
        if scheme != "file":
            raise PromotionError(
                f"cannot promote from scheme {scheme!r}; only 'file' is supported"
            )
        file_adapter = self._adapters.get("file")
        swarm_adapter = self._adapters.get("swarm")
        if file_adapter is None or swarm_adapter is None:
            raise PromotionError(
                "promote requires both 'file' and 'swarm' adapters to be registered"
            )
        try:
            artifact = await file_adapter.get(ref)
        except Exception as exc:
            raise PromotionError(f"failed to read source artifact: {exc}") from exc
        promoted = Artifact(
            content=artifact.content,
            mime=artifact.mime,
            tags=list(artifact.tags),
            provenance=dict(artifact.provenance or {}),
            attrs={**(artifact.attrs or {}), "store": "swarm"},
        )
        try:
            return await self.put(promoted)
        except Exception as exc:
            raise PromotionError(f"failed to store promoted artifact: {exc}") from exc

    def capabilities(self) -> Capabilities:
        schemes: set[str] = set()
        supports_search = False
        supports_delete = False
        for adapter in self._adapters.values():
            caps = adapter.capabilities()
            schemes |= set(caps.schemes)
            supports_search = supports_search or caps.supports_search
            supports_delete = supports_delete or caps.supports_delete
        supports_promote = "file" in self._adapters and "swarm" in self._adapters
        return Capabilities(
            schemes=frozenset(schemes),
            supports_search=supports_search,
            supports_delete=supports_delete,
            supports_promote=supports_promote,
        )
