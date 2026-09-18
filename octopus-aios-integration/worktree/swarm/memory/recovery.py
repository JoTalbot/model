"""Disaster-recovery toolkit for the Immortal Swarm memory layer.

Three pieces, each useful on its own and stronger together:

1. :class:`Replicator` — fan a single artifact (or any iterable of them)
   into many backends in parallel and report which writes succeeded.
   With 14 anonymous cloud-paste schemes + the local vault + the DHT,
   a single high-value record can be put in ~ten independent places at
   once.  As long as *one* survives, the data is recoverable.

2. :class:`SwarmSnapshot` — stream every record reachable through a
   composite memory port into a deterministic JSONL bundle (one row per
   line: ``{"ref":..., "artifact":...}``).  ``restore`` ingests the
   bundle back into any adapter.  The whole snapshot fits inside a
   single Pastebin / Telegraph page when the corpus is small, which
   matters when the LAN is gone and you have only your phone.

3. :class:`BootstrapManifest` — a tiny, self-describing JSON document
   listing the swarm's known seed peers, important refs and the
   adapters that hold them.  A node booting from cold disk reads one
   manifest, walks the refs through whichever adapters reach the
   network, and rebuilds its working set.  The manifest itself can
   live in *any* of the 14 anonymous storages, so the swarm can survive
   even when all of its own peers are gone — the only thing needed for
   takeoff is a single ``ref:<scheme>:<opaque>`` URL.

All three are dependency-free, async-first, and re-use the existing
MemoryPort / MemoryRepository abstractions.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swarm.memory.ref_parse import parse_ref
from swarm.memory.types import Artifact

# ---------------------------------------------------------------------------
# Replicator
# ---------------------------------------------------------------------------

@dataclass
class ReplicationOutcome:
    scheme: str
    ref: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.ref is not None


class Replicator:
    """Fan a single artifact into many backends in parallel.

    Backends are addressed by their composite-port scheme name; any
    adapter registered on the supplied :class:`CompositeMemoryPort`
    qualifies, including 'file', 'swarm', 'obsidian' and all paste-cloud
    schemes.
    """

    def __init__(self, memory_port) -> None:
        self._port = memory_port

    async def replicate(
        self,
        artifact: Artifact,
        *,
        schemes: Iterable[str] | None = None,
    ) -> list[ReplicationOutcome]:
        caps = self._port.capabilities()
        available = set(caps.schemes)
        targets = list(schemes) if schemes is not None else sorted(available - {"file"})
        results: list[ReplicationOutcome] = []

        async def one(scheme: str) -> ReplicationOutcome:
            if scheme not in available:
                return ReplicationOutcome(
                    scheme=scheme, error=f"adapter {scheme!r} not registered"
                )
            specific = Artifact(
                content=artifact.content,
                mime=artifact.mime,
                tags=list(artifact.tags or []),
                provenance=dict(artifact.provenance or {}),
                attrs={**(artifact.attrs or {}), "store": scheme},
            )
            try:
                ref = await self._port.put(specific)
                return ReplicationOutcome(scheme=scheme, ref=ref)
            except Exception as exc:
                return ReplicationOutcome(scheme=scheme, error=repr(exc))

        results = await asyncio.gather(*(one(s) for s in targets))
        return list(results)


# ---------------------------------------------------------------------------
# Snapshot / restore
# ---------------------------------------------------------------------------

@dataclass
class SnapshotEntry:
    ref: str
    artifact_b64: str
    mime: str
    tags: list[str]
    provenance: dict[str, Any]
    attrs: dict[str, Any]


def _artifact_to_dict(art: Artifact) -> dict[str, Any]:
    if isinstance(art.content, str):
        content_b64 = base64.b64encode(art.content.encode("utf-8")).decode("ascii")
    else:
        content_b64 = base64.b64encode(art.content).decode("ascii")
    return {
        "mime": art.mime,
        "tags": list(art.tags or []),
        "provenance": dict(art.provenance or {}),
        "attrs": dict(art.attrs or {}),
        "content_b64": content_b64,
    }


def _dict_to_artifact(raw: dict[str, Any]) -> Artifact:
    content = base64.b64decode(raw["content_b64"])
    return Artifact(
        content=content,
        mime=raw.get("mime", "application/octet-stream"),
        tags=list(raw.get("tags") or []),
        provenance=dict(raw.get("provenance") or {}),
        attrs=dict(raw.get("attrs") or {}),
    )


class SwarmSnapshot:
    """Dump / restore every reachable record through a composite memory port."""

    HEADER_KEY = "__gemaxi_snapshot__"
    VERSION = 1

    def __init__(self, memory_port) -> None:
        self._port = memory_port

    async def dump(self, *, tags: list[str] | None = None, owner: str | None = None) -> str:
        """Return a JSONL bundle (header + one line per artifact).

        Pass ``tags=[]`` (the default) to grab every searchable record.
        Adapters that don't support search are silently skipped (they
        emit nothing in the bundle but their data is still reachable by
        direct ``get`` once the ref is known).
        """
        header = {
            self.HEADER_KEY: True,
            "version": self.VERSION,
            "ts": time.time(),
            "schemes": sorted(self._port.capabilities().schemes),
        }
        lines: list[str] = [json.dumps(header, ensure_ascii=False)]
        try:
            metas = await self._port.search(list(tags or []), owner=owner)
        except Exception:
            metas = []
        for meta in metas:
            try:
                art = await self._port.get(meta.ref)
            except Exception:
                continue
            entry = {"ref": meta.ref, "artifact": _artifact_to_dict(art)}
            lines.append(json.dumps(entry, ensure_ascii=False))
        return "\n".join(lines) + "\n"

    async def dump_to_path(self, path: str | Path, **kwargs: Any) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(await self.dump(**kwargs), encoding="utf-8")
        return out

    async def restore(
        self,
        bundle: str,
        *,
        target_scheme: str | None = None,
    ) -> list[str]:
        """Replay every entry of ``bundle`` through ``put``.

        ``target_scheme`` (when given) overrides each artifact's
        ``attrs['store']`` so the whole snapshot lands in a single
        backend — handy for rehydrating a fresh node from a JSONL bundle
        fetched off a single anonymous pastebin link.
        """
        refs: list[str] = []
        lines = [ln for ln in bundle.splitlines() if ln.strip()]
        if not lines:
            return refs
        header = json.loads(lines[0])
        if not header.get(self.HEADER_KEY):
            raise ValueError("not a swarm snapshot bundle")
        for raw in lines[1:]:
            entry = json.loads(raw)
            art = _dict_to_artifact(entry["artifact"])
            if target_scheme:
                art.attrs = {**(art.attrs or {}), "store": target_scheme}
            try:
                new_ref = await self._port.put(art)
                refs.append(new_ref)
            except Exception:
                continue
        return refs

    async def restore_from_path(self, path: str | Path, **kwargs: Any) -> list[str]:
        body = Path(path).read_text(encoding="utf-8")
        return await self.restore(body, **kwargs)


# ---------------------------------------------------------------------------
# Bootstrap manifest
# ---------------------------------------------------------------------------

@dataclass
class BootstrapEntry:
    """One canonical pointer in a bootstrap manifest."""

    ref: str
    purpose: str = ""
    notes: str = ""

    @property
    def scheme(self) -> str:
        try:
            scheme, _ = parse_ref(self.ref)
            return scheme
        except Exception:
            return ""


@dataclass
class BootstrapManifest:
    """Self-describing manifest the swarm uses to bootstrap from cold state.

    Designed to be embedded in *any* anonymous pastebin so a single URL
    is enough to rejoin the swarm — even from a phone with a fresh
    browser and no saved credentials.
    """

    HEADER_KEY = "__gemaxi_manifest__"
    VERSION = 1

    seeds: list[dict[str, Any]] = field(default_factory=list)
    entries: list[BootstrapEntry] = field(default_factory=list)
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    # --- mutation ---------------------------------------------------------

    def add_seed(self, host: str, port: int, kind: str = "kademlia") -> None:
        self.seeds.append({"host": host, "port": int(port), "kind": kind})

    def add_entry(self, ref: str, *, purpose: str = "", notes: str = "") -> None:
        self.entries.append(BootstrapEntry(ref=ref, purpose=purpose, notes=notes))

    def add_replication(self, outcomes: Iterable[ReplicationOutcome], *, purpose: str) -> None:
        """Register every successful outcome from :meth:`Replicator.replicate`."""
        for o in outcomes:
            if o.ok and o.ref:
                self.add_entry(o.ref, purpose=purpose, notes=f"via {o.scheme}")

    # --- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            self.HEADER_KEY: True,
            "version": self.VERSION,
            "created_at": self.created_at,
            "notes": self.notes,
            "seeds": list(self.seeds),
            "entries": [
                {"ref": e.ref, "purpose": e.purpose, "notes": e.notes}
                for e in self.entries
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")
        return p

    @classmethod
    def from_json(cls, text: str) -> BootstrapManifest:
        raw = json.loads(text)
        if not raw.get(cls.HEADER_KEY):
            raise ValueError("not a bootstrap manifest")
        m = cls(notes=str(raw.get("notes", "")), created_at=float(raw.get("created_at", time.time())))
        for s in raw.get("seeds") or []:
            m.seeds.append({"host": str(s["host"]), "port": int(s["port"]), "kind": str(s.get("kind", "kademlia"))})
        for e in raw.get("entries") or []:
            m.add_entry(str(e["ref"]), purpose=str(e.get("purpose", "")), notes=str(e.get("notes", "")))
        return m

    @classmethod
    def load(cls, path: str | Path) -> BootstrapManifest:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    # --- network publish / fetch -----------------------------------------

    async def publish(self, replicator: Replicator, *, schemes: Iterable[str] | None = None) -> list[ReplicationOutcome]:
        """Spray the manifest itself across multiple anonymous storages.

        Returns the list of refs so the operator can write them down on
        paper — or in a Telegram saved message — for the next cold start.
        """
        art = Artifact(
            content=self.to_json(),
            mime="application/json",
            tags=["bootstrap", "manifest"],
            attrs={"kind": "bootstrap_manifest"},
        )
        return await replicator.replicate(art, schemes=schemes)

    @classmethod
    async def fetch(cls, memory_port, ref: str) -> BootstrapManifest:
        """Fetch a previously-published manifest from any reachable adapter."""
        art = await memory_port.get(ref)
        body = art.content
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        return cls.from_json(body)


# ---------------------------------------------------------------------------
# Convenience helper for repository-backed snapshot
# ---------------------------------------------------------------------------

async def snapshot_repository(repo, target_scheme: str | None = None) -> str:
    """Dump every row of a :class:`MemoryRepository` into a JSONL bundle."""
    rows = await repo.query(limit=10_000_000)
    entries: list[dict[str, Any]] = []
    for row in rows:
        entries.append(
            {
                "ref": row.ref,
                "table": row.table,
                "data": row.data,
                "tags": row.tags,
                "attrs": row.attrs,
            }
        )
    header = {
        SwarmSnapshot.HEADER_KEY: True,
        "version": SwarmSnapshot.VERSION,
        "kind": "repository",
        "ts": time.time(),
        "target_scheme": target_scheme,
        "rows": len(entries),
    }
    return "\n".join([json.dumps(header, ensure_ascii=False)] + [json.dumps(e, ensure_ascii=False) for e in entries]) + "\n"


async def restore_repository(repo, bundle: str) -> list[str]:
    refs: list[str] = []
    lines = [ln for ln in bundle.splitlines() if ln.strip()]
    if not lines:
        return refs
    header = json.loads(lines[0])
    if not header.get(SwarmSnapshot.HEADER_KEY) or header.get("kind") != "repository":
        raise ValueError("not a repository snapshot bundle")
    for raw in lines[1:]:
        entry = json.loads(raw)
        attrs = dict(entry.get("attrs") or {})
        # Strip server-managed keys so save() recreates them cleanly.
        attrs.pop("_table", None)
        ref = await repo.save(
            data=entry["data"],
            table=entry["table"],
            tags=[t for t in entry.get("tags") or [] if not t.startswith("table:")],
            attrs=attrs,
        )
        refs.append(ref)
    return refs
