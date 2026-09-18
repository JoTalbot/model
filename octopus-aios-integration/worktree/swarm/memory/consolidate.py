"""Memory consolidation: GC by TTL, exact-duplicate detection, near-dup pruning.

Long-running swarms accumulate junk: stale chat messages, retried writes,
duplicate vector-index rows, near-identical wiki notes saved minutes
apart.  This module reads (never mutates without explicit ``apply=True``)
through :class:`MemoryRepository` and produces a structured plan that
the operator can review before pulling the trigger.

API:

* :class:`ConsolidationReport`
    A summary of stale / duplicate / near-duplicate refs alongside the
    actions that would happen on apply.

* :class:`Consolidator`
    The planner / executor.  ``plan(...)`` is read-only; ``apply(...)``
    deletes refs through the underlying port (returns ``False`` for
    refs whose adapter does not support delete).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class ConsolidationReport:
    """Snapshot of the planner's verdict."""

    total: int = 0
    stale: list[str] = field(default_factory=list)
    duplicates: list[list[str]] = field(default_factory=list)
    near_duplicates: list[list[str]] = field(default_factory=list)
    deletions: list[str] = field(default_factory=list)
    deletion_failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "stale": list(self.stale),
            "duplicates": [list(g) for g in self.duplicates],
            "near_duplicates": [list(g) for g in self.near_duplicates],
            "deletions": list(self.deletions),
            "deletion_failed": list(self.deletion_failed),
            "summary": {
                "stale_count": len(self.stale),
                "duplicate_groups": len(self.duplicates),
                "near_duplicate_groups": len(self.near_duplicates),
                "would_delete": len(self.stale)
                                + sum(max(0, len(g) - 1) for g in self.duplicates),
            },
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_payload(data: dict, attrs: dict | None = None) -> bytes:
    """Stable canonical bytes for hashing equality."""
    payload = {
        "d": data,
        # Keep table + intrinsic content in the hash; skip _ts and any
        # provenance-style attrs that legitimately differ between
        # identical payloads written at different times.
        "t": (attrs or {}).get("_table"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _content_hash(data: dict, attrs: dict | None = None) -> str:
    return hashlib.blake2b(
        _canonical_payload(data, attrs), digest_size=16
    ).hexdigest()


def _shingles(text: str, k: int = 4) -> set[str]:
    """Character k-grams for near-duplicate Jaccard estimate."""
    t = " ".join(text.split()).lower()
    if len(t) <= k:
        return {t} if t else set()
    return {t[i : i + k] for i in range(len(t) - k + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Consolidator
# ---------------------------------------------------------------------------


class Consolidator:
    """Plan-then-apply memory cleanup over a :class:`MemoryRepository`.

    Parameters
    ----------
    repository:
        Wraps a memory port; we use ``query`` for the read and ``delete``
        for the write step.
    """

    def __init__(self, repository) -> None:
        self._repo = repository

    async def plan(
        self,
        *,
        table: str | None = None,
        ttl_seconds: float | None = None,
        now: float | None = None,
        near_threshold: float = 0.85,
    ) -> ConsolidationReport:
        """Build a deletion plan without mutating anything.

        Parameters
        ----------
        table:
            Restrict to a single repository table (``attrs._table``).
        ttl_seconds:
            Rows older than ``now - ttl_seconds`` (by ``attrs._ts``)
            are flagged as stale.  ``None`` disables TTL pruning.
        now:
            Override the current epoch (mostly for tests).
        near_threshold:
            Minimum Jaccard score on character 4-grams for two rows to
            be considered near-duplicates.
        """
        rows = await self._repo.query(table=table, limit=10_000_000)
        report = ConsolidationReport(total=len(rows))
        if not rows:
            return report

        clock = now if now is not None else time.time()

        # ----------------------------------------------------------------
        # 1. Stale rows by TTL
        # ----------------------------------------------------------------
        if ttl_seconds is not None and ttl_seconds > 0:
            cutoff = clock - ttl_seconds
            for r in rows:
                ts = r.attrs.get("_ts")
                if isinstance(ts, (int, float)) and ts < cutoff:
                    report.stale.append(r.ref)

        # ----------------------------------------------------------------
        # 2. Exact content duplicates
        # ----------------------------------------------------------------
        by_hash: dict[str, list] = {}
        for r in rows:
            h = _content_hash(r.data, r.attrs)
            by_hash.setdefault(h, []).append(r)
        for group in by_hash.values():
            if len(group) > 1:
                group.sort(key=lambda r: float(r.attrs.get("_ts") or 0.0))
                report.duplicates.append([r.ref for r in group])

        # ----------------------------------------------------------------
        # 3. Near-duplicates (Jaccard on character 4-grams)
        # ----------------------------------------------------------------
        if near_threshold is not None and 0 < near_threshold < 1:
            # Anything already marked as an exact duplicate is excluded
            # from the near-dup pass.
            exact_dup_refs = {ref for g in report.duplicates for ref in g}
            text_rows: list[tuple[str, str, set[str]]] = []
            for r in rows:
                if r.ref in exact_dup_refs:
                    continue
                text = str(r.data.get("text") or json.dumps(r.data, ensure_ascii=False))
                text_rows.append((r.ref, text, _shingles(text)))
            visited: set[str] = set()
            for i, (ref_a, _, sh_a) in enumerate(text_rows):
                if ref_a in visited or not sh_a:
                    continue
                cluster = [ref_a]
                visited.add(ref_a)
                for ref_b, _, sh_b in text_rows[i + 1 :]:
                    if ref_b in visited or not sh_b:
                        continue
                    if _jaccard(sh_a, sh_b) >= near_threshold:
                        cluster.append(ref_b)
                        visited.add(ref_b)
                if len(cluster) > 1:
                    report.near_duplicates.append(cluster)

        return report

    async def apply(
        self,
        report: ConsolidationReport,
        *,
        delete_stale: bool = True,
        delete_duplicates: bool = True,
        delete_near_duplicates: bool = False,
        keep_newest: bool = True,
    ) -> ConsolidationReport:
        """Execute the deletions selected by ``report`` flags.

        For each duplicate cluster, by default keeps the newest row
        (``keep_newest=True``) and deletes the rest.  Near-duplicate
        deletion is *off by default* -- false positives are easy when
        text is short.

        Mutates ``report`` in place (populates ``deletions`` /
        ``deletion_failed``) and returns it for chaining.
        """
        to_delete: list[str] = []
        if delete_stale:
            to_delete.extend(report.stale)
        if delete_duplicates:
            for group in report.duplicates:
                ordered = list(group)  # already sorted oldest->newest in plan
                survivor = ordered[-1] if keep_newest else ordered[0]
                to_delete.extend(r for r in ordered if r != survivor)
        if delete_near_duplicates:
            for group in report.near_duplicates:
                ordered = list(group)
                survivor = ordered[-1] if keep_newest else ordered[0]
                to_delete.extend(r for r in ordered if r != survivor)

        seen: set[str] = set()
        for ref in to_delete:
            if ref in seen:
                continue
            seen.add(ref)
            try:
                ok = await self._repo.delete(ref)
            except Exception:
                ok = False
            if ok:
                report.deletions.append(ref)
            else:
                report.deletion_failed.append(ref)
        return report


__all__ = ["ConsolidationReport", "Consolidator"]
