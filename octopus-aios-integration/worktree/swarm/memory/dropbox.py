"""Universal file-sharing layer over the immortal memory facade.

``FileDropbox`` lets the swarm act like a public file dropper:

    ref = await dropbox.upload("/path/to/anything.zip")
    # ref is a single short string -- share it anywhere.
    path = await dropbox.download(ref, "/where/to/save.zip")

Under the hood:

* the file is split into fixed-size chunks (default 256 KB so each chunk
  fits comfortably inside any of the 14 anonymous pastebins);
* every chunk is **replicated** to ``replication`` independent backends
  via :class:`Replicator`, so losing several cloud services still leaves
  every chunk reachable;
* a JSON manifest is built — ``{name, mime, size, sha256, chunks: [...]}``
  — and the manifest itself is replicated the same way;
* the returned ``ref`` is the manifest's own ref.  Anyone with that one
  string can rebuild the file from whichever clouds are still up.

Hash check on every chunk + on the assembled file means silent
corruption cannot sneak through; concurrent downloads (``asyncio.gather``)
keep wall-time low even when chunks are spread across far-flung backends.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swarm.memory.recovery import Replicator
from swarm.memory.ref_parse import parse_ref
from swarm.memory.types import Artifact, MemoryAdapterError, RefNotFoundError

DEFAULT_CHUNK_SIZE = 256 * 1024  # 256 KB — fits in every paste service we ship
DEFAULT_REPLICATION = 3  # each chunk lives in three independent backends


# ---------------------------------------------------------------------------
# Manifest dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChunkLocator:
    idx: int
    size: int
    sha256: str
    refs: list[str] = field(default_factory=list)


@dataclass
class DropboxManifest:
    name: str
    mime: str
    size: int
    sha256: str
    chunk_size: int
    chunks: list[ChunkLocator]
    created_at: float = field(default_factory=time.time)
    notes: str = ""

    HEADER_KEY = "__gemaxi_dropbox__"
    VERSION = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            self.HEADER_KEY: True,
            "version": self.VERSION,
            "created_at": self.created_at,
            "notes": self.notes,
            "name": self.name,
            "mime": self.mime,
            "size": self.size,
            "sha256": self.sha256,
            "chunk_size": self.chunk_size,
            "chunks": [
                {"idx": c.idx, "size": c.size, "sha256": c.sha256, "refs": list(c.refs)}
                for c in self.chunks
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> DropboxManifest:
        d = json.loads(raw)
        if not d.get(cls.HEADER_KEY):
            raise ValueError("not a gemaxi dropbox manifest")
        chunks = [
            ChunkLocator(
                idx=int(c["idx"]),
                size=int(c["size"]),
                sha256=str(c["sha256"]),
                refs=list(c.get("refs") or []),
            )
            for c in d.get("chunks") or []
        ]
        return cls(
            name=str(d.get("name") or "file"),
            mime=str(d.get("mime") or "application/octet-stream"),
            size=int(d.get("size") or 0),
            sha256=str(d.get("sha256") or ""),
            chunk_size=int(d.get("chunk_size") or DEFAULT_CHUNK_SIZE),
            chunks=chunks,
            created_at=float(d.get("created_at") or time.time()),
            notes=str(d.get("notes") or ""),
        )


@dataclass
class UploadReport:
    manifest_ref: str
    manifest: DropboxManifest
    chunk_replicas: list[int]
    manifest_replicas: int
    manifest_refs: list[str] = field(default_factory=list)

    @property
    def min_chunk_replicas(self) -> int:
        return min(self.chunk_replicas) if self.chunk_replicas else 0


# ---------------------------------------------------------------------------
# FileDropbox
# ---------------------------------------------------------------------------

ProgressFn = Callable[[str, int, int], None]


class FileDropbox:
    """Universal file dropper backed by the swarm memory facade.

    Parameters
    ----------
    memory_port :
        A composite memory port whose ``capabilities().schemes`` contains
        the desired upload targets.
    chunk_size :
        Bytes per chunk.  Default 256 KB.  Keep ≤ 1 MB so chunks fit in
        pastebins like dpaste; bigger chunks are fine for binary-blob
        backends like catbox / transfer.sh.
    replication :
        How many independent backends store each chunk.  Default 3.
    upload_schemes / manifest_schemes :
        Override the default fan-out targets.  ``None`` means "every
        non-``file`` scheme registered on the port".
    """

    DROPBOX_PREFIX = "dropbox:"

    def __init__(
        self,
        memory_port,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        replication: int = DEFAULT_REPLICATION,
        upload_schemes: list[str] | None = None,
        manifest_schemes: list[str] | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if replication <= 0:
            raise ValueError("replication must be positive")
        self._port = memory_port
        self._chunk_size = chunk_size
        self._replication = replication
        self._upload_schemes = list(upload_schemes) if upload_schemes else None
        self._manifest_schemes = (
            list(manifest_schemes) if manifest_schemes else None
        )
        self._replicator = Replicator(memory_port)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _available_schemes(self) -> list[str]:
        return sorted(self._port.capabilities().schemes)

    def _pick_targets(self, override: list[str] | None) -> list[str]:
        if override is not None:
            return list(override)
        available = self._available_schemes()
        # Prefer non-local backends: "file" alone defeats the redundancy goal.
        return [s for s in available if s != "file"]

    def _round_robin_subset(self, schemes: list[str], k: int, offset: int) -> list[str]:
        if not schemes:
            return []
        k = min(k, len(schemes))
        n = len(schemes)
        return [schemes[(offset + i) % n] for i in range(k)]

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload(
        self,
        source: str | Path | bytes,
        *,
        name: str | None = None,
        mime: str | None = None,
        notes: str = "",
        progress: ProgressFn | None = None,
    ) -> UploadReport:
        """Upload a file (or in-memory bytes) and return an :class:`UploadReport`.

        ``progress("chunk"|"manifest", done, total)`` is called after each
        successful chunk upload and once at the end of the manifest spray.
        """
        data, computed_name, computed_mime = self._load_source(source, name, mime)
        total_sha = self._sha256(data)
        chunks_bytes = [
            data[i : i + self._chunk_size]
            for i in range(0, len(data), self._chunk_size)
        ] or [b""]  # always upload at least one (possibly empty) chunk

        targets = self._pick_targets(self._upload_schemes)
        if not targets:
            raise MemoryAdapterError(
                "no upload targets: register at least one non-file adapter "
                "or pass upload_schemes=[...]"
            )

        locators: list[ChunkLocator] = [
            ChunkLocator(idx=i, size=len(b), sha256=self._sha256(b))
            for i, b in enumerate(chunks_bytes)
        ]

        async def upload_chunk(idx: int, blob: bytes) -> tuple[int, list[str]]:
            chosen = self._round_robin_subset(targets, self._replication, idx)
            outcomes = await self._replicator.replicate(
                Artifact(
                    content=blob,
                    mime="application/octet-stream",
                    tags=["dropbox", "chunk"],
                    attrs={
                        "kind": "dropbox_chunk",
                        "chunk_idx": idx,
                        "chunk_sha256": locators[idx].sha256,
                    },
                ),
                schemes=chosen,
            )
            ok_refs = [o.ref for o in outcomes if o.ok and o.ref]
            return idx, ok_refs

        chunk_results = await asyncio.gather(
            *(upload_chunk(i, b) for i, b in enumerate(chunks_bytes))
        )
        for idx, refs in chunk_results:
            locators[idx].refs = refs
            if progress:
                progress("chunk", idx + 1, len(locators))

        missing = [c.idx for c in locators if not c.refs]
        if missing:
            raise MemoryAdapterError(
                f"upload failed: chunks with zero replicas {missing!r}"
            )

        manifest = DropboxManifest(
            name=computed_name,
            mime=computed_mime,
            size=len(data),
            sha256=total_sha,
            chunk_size=self._chunk_size,
            chunks=locators,
            notes=notes,
        )

        manifest_targets = self._pick_targets(self._manifest_schemes)
        if not manifest_targets:
            raise MemoryAdapterError(
                "no manifest targets: register at least one non-file adapter "
                "or pass manifest_schemes=[...]"
            )
        manifest_subset = self._round_robin_subset(
            manifest_targets, self._replication, 0
        )
        manifest_outcomes = await self._replicator.replicate(
            Artifact(
                content=manifest.to_json(),
                mime="application/json",
                tags=["dropbox", "manifest"],
                attrs={"kind": "dropbox_manifest", "name": computed_name},
            ),
            schemes=manifest_subset,
        )
        manifest_refs = [o.ref for o in manifest_outcomes if o.ok and o.ref]
        if not manifest_refs:
            raise MemoryAdapterError("manifest upload failed on every target")

        if progress:
            progress("manifest", len(manifest_refs), len(manifest_subset))

        return UploadReport(
            manifest_ref=manifest_refs[0],
            manifest=manifest,
            chunk_replicas=[len(c.refs) for c in locators],
            manifest_replicas=len(manifest_refs),
            manifest_refs=manifest_refs,
        )

    @staticmethod
    def _load_source(
        source: str | Path | bytes,
        name_override: str | None,
        mime_override: str | None,
    ) -> tuple[bytes, str, str]:
        if isinstance(source, (bytes, bytearray)):
            return (
                bytes(source),
                name_override or "blob.bin",
                mime_override or "application/octet-stream",
            )
        p = Path(source)
        if not p.is_file():
            raise FileNotFoundError(p)
        data = p.read_bytes()
        name = name_override or p.name
        mime = mime_override or (
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        return data, name, mime

    # ------------------------------------------------------------------
    # Inspection / download
    # ------------------------------------------------------------------

    async def fetch_manifest(self, ref: str | list[str]) -> DropboxManifest:
        """Resolve a manifest by ref; accepts ``dropbox:`` shorthand or list.

        When ``ref`` is a list of mirror refs, the first reachable one wins —
        so even if one anonymous storage dies the manifest is still
        recoverable.
        """
        candidates = [ref] if isinstance(ref, str) else list(ref)
        last_error: Exception | None = None
        for raw in candidates:
            actual_ref = self._strip_prefix(raw)
            try:
                scheme, _ = parse_ref(actual_ref)
            except Exception as exc:
                last_error = exc
                continue
            if scheme not in self._port.capabilities().schemes:
                last_error = MemoryAdapterError(
                    f"adapter for scheme {scheme!r} not registered on this port"
                )
                continue
            try:
                art = await self._port.get(actual_ref)
            except Exception as exc:
                last_error = exc
                continue
            body = art.content
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            try:
                return DropboxManifest.from_json(body)
            except Exception as exc:
                last_error = exc
                continue
        raise MemoryAdapterError(
            f"manifest unreadable from every candidate ref ({len(candidates)} tried;"
            f" last={last_error})"
        )

    async def info(self, ref: str | list[str]) -> dict[str, Any]:
        manifest = await self.fetch_manifest(ref)
        d = manifest.to_dict()
        d.pop(DropboxManifest.HEADER_KEY, None)
        d["chunks"] = [
            {**c, "replicas": len(c["refs"])} for c in d["chunks"]
        ]
        d["min_replicas"] = min((len(c.refs) for c in manifest.chunks), default=0)
        return d

    async def download(
        self,
        ref: str | list[str],
        destination: str | Path,
        *,
        progress: ProgressFn | None = None,
    ) -> Path:
        """Reassemble the file referenced by ``ref`` at ``destination``."""
        manifest = await self.fetch_manifest(ref)
        dst = Path(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        chunks_bytes: list[bytes] = [b""] * len(manifest.chunks)

        async def fetch_one(loc: ChunkLocator) -> tuple[int, bytes]:
            last_error: Exception | None = None
            for candidate in loc.refs:
                try:
                    art = await self._port.get(candidate)
                except (MemoryAdapterError, RefNotFoundError) as exc:
                    last_error = exc
                    continue
                blob = art.content
                if isinstance(blob, str):
                    blob = blob.encode("utf-8")
                # Some text-only adapters envelope blobs already — paste_cloud
                # uses an inner JSON envelope; LocalScratch returns raw bytes.
                if self._sha256(blob) != loc.sha256:
                    last_error = MemoryAdapterError(
                        f"chunk {loc.idx}: sha256 mismatch via {candidate}"
                    )
                    continue
                return loc.idx, blob
            raise MemoryAdapterError(
                f"chunk {loc.idx}: every replica unreadable "
                f"({len(loc.refs)} tried; last={last_error})"
            )

        results = await asyncio.gather(*(fetch_one(c) for c in manifest.chunks))
        for idx, blob in results:
            chunks_bytes[idx] = blob
            if progress:
                progress("chunk", idx + 1, len(manifest.chunks))

        assembled = b"".join(chunks_bytes)
        if self._sha256(assembled) != manifest.sha256:
            raise MemoryAdapterError(
                f"assembled file sha256 mismatch (expected {manifest.sha256})"
            )
        if len(assembled) != manifest.size:
            raise MemoryAdapterError(
                f"assembled file size {len(assembled)} != manifest {manifest.size}"
            )
        dst.write_bytes(assembled)
        if progress:
            progress("manifest", 1, 1)
        return dst

    # ------------------------------------------------------------------
    # Ref helpers
    # ------------------------------------------------------------------

    @classmethod
    def dropbox_ref(cls, ref: str) -> str:
        """Return a user-friendly shorthand ``dropbox:<ref>``."""
        if ref.startswith(cls.DROPBOX_PREFIX):
            return ref
        return cls.DROPBOX_PREFIX + ref

    @classmethod
    def _strip_prefix(cls, ref: str) -> str:
        if ref.startswith(cls.DROPBOX_PREFIX):
            return ref[len(cls.DROPBOX_PREFIX) :]
        return ref

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def health(self, ref: str | list[str]) -> dict[str, Any]:
        """Probe every chunk replica with ``exists()`` and return a report."""
        manifest = await self.fetch_manifest(ref)
        chunk_health: list[dict[str, Any]] = []
        for loc in manifest.chunks:
            alive: list[str] = []
            dead: list[str] = []
            for candidate in loc.refs:
                try:
                    ok = await self._port.exists(candidate)
                except Exception:
                    ok = False
                (alive if ok else dead).append(candidate)
            chunk_health.append(
                {"idx": loc.idx, "alive": alive, "dead": dead, "replicas": len(loc.refs)}
            )
        return {
            "name": manifest.name,
            "size": manifest.size,
            "chunks": chunk_health,
            "recoverable": all(c["alive"] for c in chunk_health),
        }


# ---------------------------------------------------------------------------
# Convenience module-level wrappers
# ---------------------------------------------------------------------------

async def upload_file(memory_port, path: str | Path, **kwargs: Any) -> UploadReport:
    return await FileDropbox(memory_port).upload(path, **kwargs)


async def download_file(
    memory_port, ref: str, destination: str | Path, **kwargs: Any
) -> Path:
    return await FileDropbox(memory_port).download(ref, destination, **kwargs)
