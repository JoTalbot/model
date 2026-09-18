"""Append-only audit log for every memory operation.

Two pieces:

* :class:`AuditLog`
    Append-only JSONL store on disk.  One line per event, atomic ``open``
    + ``write`` + ``fsync`` so a crashed agent leaves at most one half-line
    on disk (and ``query`` skips malformed lines).  When ``rotate_daily``
    is enabled, filenames roll over by UTC date; otherwise everything
    appends to a single ``audit.jsonl``.

* :class:`AuditedMemoryPort`
    Middleware over any ``MemoryPort``.  Every ``put`` / ``get`` /
    ``delete`` / ``promote`` records ``{ts, op, ref, scheme, ok, bytes,
    latency_ms, agent_id, error}`` to the log before returning the result.

Audit log is *append-only by contract* — :class:`AuditLog` exposes no
delete/edit methods.  Wipe the file from outside if you really need to.

Event schema (one JSON line)::

    {
        "ts":         "2026-05-13T18:42:00.123456+00:00",
        "op":         "put" | "get" | "delete" | "promote" | "search",
        "ref":        "ref:catbox:https://...",
        "scheme":     "catbox" | None,
        "ok":         true | false,
        "bytes":      1234,
        "latency_ms": 42.5,
        "agent_id":   "node-abc" | None,
        "error":      "RefNotFoundError: ..." | None,
        "meta":       { ...optional caller-supplied fields... }
    }
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any

from swarm.memory.types import Artifact, Capabilities, RefMeta

# ---------------------------------------------------------------------------
# AuditLog — append-only JSONL store
# ---------------------------------------------------------------------------


class AuditLog:
    """Append-only JSONL audit log with optional daily rotation.

    Thread-safe via an internal ``threading.Lock``.  Suitable for
    cross-coroutine writes since ``asyncio`` shares a single thread by
    default (and any actual cross-thread access still serialises).

    Parameters
    ----------
    root:
        Directory that holds the rotating ``audit-YYYY-MM-DD.jsonl``
        files.  Created on first write.
    rotate_daily:
        If ``True``, every write picks the file whose date matches the
        event's UTC date.  If ``False``, all events append to
        ``audit.jsonl`` under ``root``.
    """

    def __init__(self, root: str | os.PathLike, *, rotate_daily: bool = True) -> None:
        self._root = Path(root).expanduser()
        self._rotate_daily = rotate_daily
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, event: dict[str, Any]) -> None:
        """Append a single event dict as one JSON line."""
        if "ts" not in event:
            event["ts"] = datetime.now(UTC).isoformat()
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        path = self._path_for(event["ts"])
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                with contextlib.suppress(OSError):
                    os.fsync(fh.fileno())

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def iter_events(
        self,
        *,
        op: str | None = None,
        ref: str | None = None,
        scheme: str | None = None,
        ok: bool | None = None,
        agent_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Iterate over events matching the given filters.

        Filters that are ``None`` are ignored.  ``since`` and ``until``
        are ISO-8601 strings compared lexicographically (UTC ISO sorts).
        """
        for path in sorted(self._all_files()):
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if op is not None and ev.get("op") != op:
                        continue
                    if ref is not None and ev.get("ref") != ref:
                        continue
                    if scheme is not None and ev.get("scheme") != scheme:
                        continue
                    if ok is not None and ev.get("ok") is not ok:
                        continue
                    if agent_id is not None and ev.get("agent_id") != agent_id:
                        continue
                    ts = ev.get("ts", "")
                    if since is not None and ts < since:
                        continue
                    if until is not None and ts > until:
                        continue
                    yield ev

    def query(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Materialise :meth:`iter_events` into a list (convenience)."""
        return list(self.iter_events(**kwargs))

    def stats(self) -> dict[str, Any]:
        """Aggregate per-op / per-scheme counters from the entire log."""
        per_op: dict[str, int] = {}
        per_scheme_ok: dict[str, int] = {}
        per_scheme_err: dict[str, int] = {}
        bytes_total = 0
        total = 0
        first_ts: str | None = None
        last_ts: str | None = None
        for ev in self.iter_events():
            total += 1
            op = ev.get("op") or "?"
            per_op[op] = per_op.get(op, 0) + 1
            scheme = ev.get("scheme") or "?"
            bucket = per_scheme_ok if ev.get("ok") else per_scheme_err
            bucket[scheme] = bucket.get(scheme, 0) + 1
            bytes_total += int(ev.get("bytes") or 0)
            ts = ev.get("ts")
            if ts:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
        return {
            "total": total,
            "per_op": per_op,
            "per_scheme_ok": per_scheme_ok,
            "per_scheme_err": per_scheme_err,
            "bytes_total": bytes_total,
            "first_ts": first_ts,
            "last_ts": last_ts,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _path_for(self, ts: str) -> Path:
        if not self._rotate_daily:
            return self._root / "audit.jsonl"
        date_part = ts[:10] if len(ts) >= 10 else datetime.now(UTC).strftime("%Y-%m-%d")
        return self._root / f"audit-{date_part}.jsonl"

    def _all_files(self) -> list[Path]:
        if not self._root.exists():
            return []
        if not self._rotate_daily:
            single = self._root / "audit.jsonl"
            return [single] if single.exists() else []
        return [
            p for p in self._root.iterdir()
            if p.is_file() and p.name.startswith("audit-") and p.suffix == ".jsonl"
        ]


# ---------------------------------------------------------------------------
# AuditedMemoryPort — middleware
# ---------------------------------------------------------------------------


def _scheme_of(ref: str | None) -> str | None:
    if not ref:
        return None
    if not ref.startswith("ref:"):
        return None
    parts = ref.split(":", 2)
    return parts[1] if len(parts) >= 2 else None


def _content_bytes(art: Artifact) -> int:
    content = art.content
    if isinstance(content, bytes):
        return len(content)
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    return 0


class AuditedMemoryPort:
    """MemoryPort middleware that journals every operation.

    Wraps an inner port.  All forwarding is direct (delegates capabilities,
    metrics, etc.); the only side-effect is one ``AuditLog.append`` per
    completed call (success *or* failure).

    Parameters
    ----------
    inner:
        Any object implementing the ``MemoryPort`` protocol.
    log:
        :class:`AuditLog` instance to write to.
    agent_id:
        Optional identifier of the calling agent.  Stamped on every
        event so a multi-node deployment can see who wrote what.
    """

    def __init__(self, inner, log: AuditLog, *, agent_id: str | None = None) -> None:
        self._inner = inner
        self._log = log
        self._agent_id = agent_id

    @property
    def metrics(self):
        return self._inner.metrics

    def capabilities(self) -> Capabilities:
        return self._inner.capabilities()

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    async def put(self, artifact: Artifact) -> str:
        size = _content_bytes(artifact)
        t0 = time.perf_counter()
        ref: str | None = None
        ok = False
        err: str | None = None
        try:
            ref = await self._inner.put(artifact)
            ok = True
            return ref
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record("put", ref=ref, ok=ok, error=err, t0=t0, size_bytes=size)

    async def get(self, ref: str) -> Artifact:
        t0 = time.perf_counter()
        ok = False
        err: str | None = None
        size = 0
        try:
            art = await self._inner.get(ref)
            size = _content_bytes(art)
            ok = True
            return art
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record("get", ref=ref, ok=ok, error=err, t0=t0, size_bytes=size)

    async def exists(self, ref: str) -> bool:
        t0 = time.perf_counter()
        ok = False
        err: str | None = None
        result = False
        try:
            result = await self._inner.exists(ref)
            ok = True
            return result
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record(
                "exists", ref=ref, ok=ok, error=err, t0=t0,
                size_bytes=0, meta={"result": result},
            )

    async def delete(self, ref: str) -> bool:
        t0 = time.perf_counter()
        ok = False
        err: str | None = None
        result = False
        try:
            result = await self._inner.delete(ref)
            ok = True
            return result
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record(
                "delete", ref=ref, ok=ok, error=err, t0=t0,
                size_bytes=0, meta={"result": result},
            )

    async def search(self, tags: list[str], owner: str | None = None) -> list[RefMeta]:
        t0 = time.perf_counter()
        ok = False
        err: str | None = None
        count = 0
        try:
            results = await self._inner.search(tags, owner=owner)
            count = len(results)
            ok = True
            return results
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record(
                "search", ref=None, ok=ok, error=err, t0=t0,
                size_bytes=0, meta={"tags": list(tags), "owner": owner, "count": count},
            )

    async def promote(self, ref: str) -> str:
        t0 = time.perf_counter()
        ok = False
        err: str | None = None
        new_ref: str | None = None
        try:
            if not hasattr(self._inner, "promote"):
                raise RuntimeError("inner port does not support promote")
            new_ref = await self._inner.promote(ref)
            ok = True
            return new_ref
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record(
                "promote", ref=ref, ok=ok, error=err, t0=t0,
                size_bytes=0, meta={"new_ref": new_ref},
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record(
        self,
        op: str,
        *,
        ref: str | None,
        ok: bool,
        error: str | None,
        t0: float,
        size_bytes: int,
        meta: dict[str, Any] | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "op": op,
            "ref": ref,
            "scheme": _scheme_of(ref),
            "ok": ok,
            "bytes": int(size_bytes),
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "agent_id": self._agent_id,
            "error": error,
        }
        if meta:
            event["meta"] = meta
        try:  # noqa: SIM105  # noqa: SIM105
            self._log.append(event)
        except Exception:
            # Never let an audit-log failure break a real memory op.
            # In production you'd plug a fallback sink; here we swallow.
            pass


__all__ = ["AuditLog", "AuditedMemoryPort"]
