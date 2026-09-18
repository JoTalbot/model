"""Health-check toolkit for refs scattered across the immortal memory facade.

``memory doctor`` over the CLI pings every supplied ref through the
configured composite memory port and reports which ones are still
reachable -- without downloading the underlying content.

The toolkit is purely client-side: it never opens an envelope, never
decrypts, never verifies a signature.  It just answers one question:
"is this ref still gettable RIGHT NOW?" -- the cheapest possible probe
that survives a half-dead pastebin or an offline DHT peer.

Public API:

* :func:`probe_ref(port, ref, timeout)` -> :class:`RefHealth`
* :func:`probe_many(port, refs, ...)` -> list[:class:`RefHealth`]
* :func:`summarize(results)` -> dict of aggregate counters
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass


@dataclass
class RefHealth:
    """Health-probe result for a single ref."""

    ref: str
    scheme: str | None
    healthy: bool
    latency_ms: float
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _scheme_of(ref: str) -> str | None:
    if not ref or not ref.startswith("ref:"):
        return None
    parts = ref.split(":", 2)
    return parts[1] if len(parts) >= 2 else None


async def probe_ref(
    port,
    ref: str,
    *,
    timeout: float = 8.0,
) -> RefHealth:
    """Probe one ref via ``port.exists`` with a hard timeout.

    Always succeeds at returning a :class:`RefHealth` -- network errors,
    adapter exceptions and timeouts all collapse into ``healthy=False``
    with a populated ``error`` string.
    """
    scheme = _scheme_of(ref)
    t0 = time.perf_counter()
    try:
        exists = await asyncio.wait_for(port.exists(ref), timeout=timeout)
    except TimeoutError:
        return RefHealth(
            ref=ref,
            scheme=scheme,
            healthy=False,
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            error=f"timeout>{timeout}s",
        )
    except Exception as exc:
        return RefHealth(
            ref=ref,
            scheme=scheme,
            healthy=False,
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            error=f"{type(exc).__name__}: {exc}",
        )
    return RefHealth(
        ref=ref,
        scheme=scheme,
        healthy=bool(exists),
        latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        error=None if exists else "not found",
    )


async def probe_many(
    port,
    refs: list[str],
    *,
    timeout: float = 8.0,
    concurrency: int = 8,
) -> list[RefHealth]:
    """Probe every ref in parallel with a ``concurrency`` semaphore.

    Returns one :class:`RefHealth` per input ref, preserving order.
    Empty input returns an empty list (so the CLI can no-op safely).
    """
    if not refs:
        return []
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(r: str) -> RefHealth:
        async with semaphore:
            return await probe_ref(port, r, timeout=timeout)

    return await asyncio.gather(*[_one(r) for r in refs])


def summarize(results: list[RefHealth]) -> dict:
    """Aggregate counters over a :class:`RefHealth` list.

    Reports total, healthy/broken counts, per-scheme split,
    average / p50 / p95 latency in ms.  Empty input yields zeros.
    """
    if not results:
        return {
            "total": 0,
            "healthy": 0,
            "broken": 0,
            "per_scheme_healthy": {},
            "per_scheme_broken": {},
            "latency_ms_avg": 0.0,
            "latency_ms_p50": 0.0,
            "latency_ms_p95": 0.0,
        }
    healthy_count = sum(1 for r in results if r.healthy)
    broken_count = len(results) - healthy_count
    per_scheme_h: dict[str, int] = {}
    per_scheme_b: dict[str, int] = {}
    for r in results:
        scheme = r.scheme or "?"
        bucket = per_scheme_h if r.healthy else per_scheme_b
        bucket[scheme] = bucket.get(scheme, 0) + 1
    latencies = sorted(r.latency_ms for r in results)
    avg = sum(latencies) / len(latencies)
    p50_idx = max(0, int(len(latencies) * 0.5) - 1) if len(latencies) > 1 else 0
    p95_idx = max(0, int(len(latencies) * 0.95) - 1) if len(latencies) > 1 else 0
    return {
        "total": len(results),
        "healthy": healthy_count,
        "broken": broken_count,
        "per_scheme_healthy": per_scheme_h,
        "per_scheme_broken": per_scheme_b,
        "latency_ms_avg": round(avg, 2),
        "latency_ms_p50": round(latencies[p50_idx], 2),
        "latency_ms_p95": round(latencies[p95_idx], 2),
    }


def format_report(results: list[RefHealth], summary: dict) -> str:
    """Human-readable rendering for the CLI (text mode)."""
    lines = []
    for r in results:
        flag = "OK " if r.healthy else "ERR"
        lat = f"{r.latency_ms:>7.1f}ms"
        scheme = (r.scheme or "?")[:14]
        detail = r.error or ""
        lines.append(f"  [{flag}] {scheme:<14} {lat}  {r.ref}  {detail}")
    if not lines:
        lines.append("  (no refs supplied)")
    lines.append("")
    lines.append(
        f"  total={summary['total']} "
        f"healthy={summary['healthy']} "
        f"broken={summary['broken']} "
        f"p50={summary['latency_ms_p50']}ms "
        f"p95={summary['latency_ms_p95']}ms"
    )
    if summary["per_scheme_broken"]:
        lines.append(f"  broken by scheme: {summary['per_scheme_broken']}")
    return "\n".join(lines)


__all__ = [
    "RefHealth",
    "format_report",
    "probe_many",
    "probe_ref",
    "summarize",
]
