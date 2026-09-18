"""Smart routing helpers built on top of :class:`MemoryMetrics`.

The composite memory port tracks per-scheme availability, latency,
volume and error counters.  This module turns those numbers into
decisions: given N independent backends, *which* ones should host the
next replica?

Two knobs make the math useful in practice:

* ``score(scheme, metrics)`` collapses one adapter's signal into a
  single float in ``[0, 1+ε]``.  Optimistic by default — schemes with
  no observed traffic score 1.0 so the swarm explores fresh backends.
* ``rank_schemes(schemes, metrics)`` sorts an iterable by score in
  descending order, falling back to alphabetical for ties (stable).

:class:`SmartReplicator` is a thin subclass of :class:`Replicator` that
uses ``rank_schemes`` to pick the top-K backends automatically, and can
loop with fresh fallbacks until ``min_replicas`` successful writes have
been collected (or the candidate pool is exhausted).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from swarm.memory.port import MemoryMetrics
from swarm.memory.recovery import ReplicationOutcome, Replicator
from swarm.memory.types import Artifact, MemoryAdapterError

# Latency decay constant: a scheme with p95 ~ this value drops to ~37 % of its
# availability-only score.  Tuned so 250 ms is "fast", 2 s is "slow".
_LATENCY_HALFLIFE_S = 1.0
# Small epsilon so a brand-new scheme outscores a fully-broken one.
_EPSILON = 1e-6


@dataclass(frozen=True)
class SchemeScore:
    scheme: str
    score: float
    availability: float
    latency_p95_ms: float | None
    puts: int
    last_error: str = ""


def score(scheme: str, metrics: MemoryMetrics) -> SchemeScore:
    """Return a :class:`SchemeScore` for one scheme.

    Formula::

        score = availability * exp(-p95_latency_seconds / HALFLIFE)

    Schemes with no observed gets are treated as 100 % available
    (optimism); schemes with no latency samples skip the decay term.
    """
    avail = metrics.availability(scheme)
    p95 = metrics.percentile(scheme, "put", 0.95)
    if p95 is None:
        p95 = metrics.percentile(scheme, "get", 0.95)
    decay = math.exp(-(p95 or 0.0) / _LATENCY_HALFLIFE_S) if p95 else 1.0
    raw = avail * decay
    if raw <= 0:
        raw = _EPSILON
    return SchemeScore(
        scheme=scheme,
        score=raw,
        availability=avail,
        latency_p95_ms=(None if p95 is None else round(p95 * 1000, 2)),
        puts=metrics.puts.get(scheme, 0),
        last_error=metrics.last_error.get(scheme, ""),
    )


def rank_schemes(
    schemes: Iterable[str], metrics: MemoryMetrics
) -> list[SchemeScore]:
    """Return ``schemes`` sorted by score descending (stable on ties)."""
    items = [score(s, metrics) for s in schemes]
    items.sort(key=lambda x: (-x.score, x.scheme))
    return items


def select_top(
    schemes: Iterable[str], metrics: MemoryMetrics, k: int
) -> list[str]:
    """Pick the top-``k`` scheme names by score."""
    ranked = rank_schemes(list(schemes), metrics)
    return [r.scheme for r in ranked[: max(0, k)]]


# ---------------------------------------------------------------------------
# SmartReplicator
# ---------------------------------------------------------------------------

class SmartReplicator(Replicator):
    """Replicator that picks targets by score and retries with fallbacks.

    Parameters added on top of :class:`Replicator`:

    * ``budget``         — total number of *attempts* the replicator may
                           make.  Defaults to ``len(candidate_pool)``.
    * ``min_replicas``   — keep recruiting fallbacks until this many puts
                           succeeded, or the candidate pool runs out.
    * ``forbid``         — set of schemes never to use (e.g. dead ones).
    """

    DEFAULT_FORBID = frozenset({"file"})

    async def smart_replicate(
        self,
        artifact: Artifact,
        *,
        k: int = 3,
        min_replicas: int | None = None,
        budget: int | None = None,
        forbid: Iterable[str] | None = None,
        candidate_pool: Iterable[str] | None = None,
    ) -> list[ReplicationOutcome]:
        caps = self._port.capabilities()
        available = set(caps.schemes)
        forbidden = set(forbid) if forbid is not None else set(self.DEFAULT_FORBID)
        pool = (
            [s for s in candidate_pool if s in available and s not in forbidden]
            if candidate_pool is not None
            else [s for s in available if s not in forbidden]
        )
        if not pool:
            raise MemoryAdapterError(
                "no candidate schemes: register at least one non-forbidden adapter"
            )
        if min_replicas is None:
            min_replicas = k
        if budget is None:
            budget = len(pool)

        metrics = getattr(self._port, "metrics", None)
        ranked = (
            [s.scheme for s in rank_schemes(pool, metrics)]
            if metrics is not None
            else sorted(pool)
        )

        results: list[ReplicationOutcome] = []
        successes = 0
        attempts = 0
        # First wave: top-k in parallel.
        wave = ranked[:k]
        ranked = ranked[k:]
        while wave and attempts < budget:
            slice_size = min(len(wave), budget - attempts)
            batch = wave[:slice_size]
            wave = wave[slice_size:]
            attempts += slice_size
            batch_outcomes = await self.replicate(artifact, schemes=batch)
            results.extend(batch_outcomes)
            successes += sum(1 for o in batch_outcomes if o.ok)
            if successes >= min_replicas:
                break
            # Refill wave with fallbacks until either we have enough or
            # the candidate pool is exhausted.
            needed = max(0, min_replicas - successes)
            if needed and ranked:
                take = min(needed, len(ranked), budget - attempts)
                if take > 0:
                    wave.extend(ranked[:take])
                    ranked = ranked[take:]

        return results
