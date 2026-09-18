from __future__ import annotations

import time
from bisect import insort
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from swarm.memory.types import Artifact, Capabilities, RefMeta

if TYPE_CHECKING:
    pass


class MemoryMetrics:
    """Per-scheme counters, latency samples, byte volumes and availability.

    All counters and samples are kept in plain dicts to avoid heavy deps.
    Latency samples are bucketed per (scheme, op) — only the last
    ``_max_samples`` values are kept to bound memory.
    """

    _max_samples: int = 2048

    def __init__(self) -> None:
        self.puts: dict[str, int] = {}
        self.gets_ok: dict[str, int] = {}
        self.gets_err: dict[str, int] = {}
        # bytes counters: scheme -> total bytes
        self.bytes_in: dict[str, int] = {}
        self.bytes_out: dict[str, int] = {}
        # latency samples: (scheme, op) -> sorted list of seconds
        self._lat_samples: dict[tuple[str, str], list[float]] = {}
        # last-error message per scheme (for /health endpoint style)
        self.last_error: dict[str, str] = {}
        self._created_at = time.time()

    # ------------------------------------------------------------------
    # Counter helpers
    # ------------------------------------------------------------------

    def record_put(self, scheme: str) -> None:
        self.puts[scheme] = self.puts.get(scheme, 0) + 1

    def record_get(self, scheme: str, *, ok: bool) -> None:
        d = self.gets_ok if ok else self.gets_err
        d[scheme] = d.get(scheme, 0) + 1

    def record_bytes_in(self, scheme: str, n: int) -> None:
        if n <= 0:
            return
        self.bytes_in[scheme] = self.bytes_in.get(scheme, 0) + n

    def record_bytes_out(self, scheme: str, n: int) -> None:
        if n <= 0:
            return
        self.bytes_out[scheme] = self.bytes_out.get(scheme, 0) + n

    def record_latency(self, scheme: str, op: str, seconds: float) -> None:
        if seconds < 0:
            return
        key = (scheme, op)
        samples = self._lat_samples.setdefault(key, [])
        insort(samples, float(seconds))
        if len(samples) > self._max_samples:
            del samples[0]

    def record_error(self, scheme: str, message: str) -> None:
        self.last_error[scheme] = (message or "")[:256]

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def percentile(self, scheme: str, op: str, p: float) -> float | None:
        """Return latency percentile in seconds; ``None`` if no samples."""
        samples = self._lat_samples.get((scheme, op)) or []
        if not samples:
            return None
        if p <= 0:
            return samples[0]
        if p >= 1:
            return samples[-1]
        idx = max(0, min(len(samples) - 1, round(p * (len(samples) - 1))))
        return samples[idx]

    def availability(self, scheme: str) -> float:
        """Fraction of ``get`` calls that succeeded for this scheme (0..1).

        Returns 1.0 when there are no observations yet.
        """
        ok = self.gets_ok.get(scheme, 0)
        err = self.gets_err.get(scheme, 0)
        total = ok + err
        if total == 0:
            return 1.0
        return ok / total

    def schemes(self) -> list[str]:
        s: set[str] = set()
        s.update(self.puts.keys())
        s.update(self.gets_ok.keys())
        s.update(self.gets_err.keys())
        s.update(self.bytes_in.keys())
        s.update(self.bytes_out.keys())
        return sorted(s)

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Return a JSON-serialisable per-scheme metrics view."""
        out: dict[str, dict[str, object]] = {}
        for scheme in self.schemes():
            put_lat = self.percentile(scheme, "put", 0.95)
            get_lat = self.percentile(scheme, "get", 0.95)
            put_med = self.percentile(scheme, "put", 0.5)
            get_med = self.percentile(scheme, "get", 0.5)
            out[scheme] = {
                "puts": self.puts.get(scheme, 0),
                "gets_ok": self.gets_ok.get(scheme, 0),
                "gets_err": self.gets_err.get(scheme, 0),
                "bytes_in": self.bytes_in.get(scheme, 0),
                "bytes_out": self.bytes_out.get(scheme, 0),
                "availability": round(self.availability(scheme), 4),
                "latency_put_p50_ms": (
                    None if put_med is None else round(put_med * 1000, 2)
                ),
                "latency_put_p95_ms": (
                    None if put_lat is None else round(put_lat * 1000, 2)
                ),
                "latency_get_p50_ms": (
                    None if get_med is None else round(get_med * 1000, 2)
                ),
                "latency_get_p95_ms": (
                    None if get_lat is None else round(get_lat * 1000, 2)
                ),
                "last_error": self.last_error.get(scheme, ""),
            }
        return out


@runtime_checkable
class MemoryAdapter(Protocol):
    scheme: str

    async def put(self, artifact: Artifact) -> str: ...
    async def get(self, ref: str) -> Artifact: ...
    async def exists(self, ref: str) -> bool: ...
    async def delete(self, ref: str) -> bool: ...
    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]: ...
    def capabilities(self) -> Capabilities: ...


@runtime_checkable
class MemoryPort(Protocol):
    async def put(self, artifact: Artifact) -> str: ...
    async def get(self, ref: str) -> Artifact: ...
    async def exists(self, ref: str) -> bool: ...
    async def delete(self, ref: str) -> bool: ...
    async def search(self, tags: list[str], owner: str | None = None) -> list[RefMeta]: ...
    async def promote(self, ref: str) -> str: ...
    def capabilities(self) -> Capabilities: ...
    @property
    def metrics(self) -> MemoryMetrics: ...
