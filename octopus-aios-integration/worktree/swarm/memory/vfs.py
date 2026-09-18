from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from swarm.memory.repository import MemoryRepository, MemoryRow
from swarm.memory.types import Artifact
from swarm.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

@dataclass
class VFile:
    id: str
    name: str
    path: str
    size: int
    mime: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    ref: str | None = None

class VirtualFileSystem:
    """Virtual File System that maps files to the semantic memory graph."""

    TABLE = "vfs_files"

    def __init__(self, repository: MemoryRepository, vector_store: VectorStore) -> None:
        self._repo = repository
        self._vectors = vector_store

    async def store_file(
        self,
        name: str,
        content: bytes | str,
        path: str = "/",
        tags: list[str] | None = None,
        mime: str = "application/octet-stream"
    ) -> VFile:
        """Store a file in the VFS and index it semantically."""

        # 1. Prepare metadata
        file_size = len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))
        file_id = f"vfs:{path.strip('/')}/{name}".replace("//", "/")

        # 2. Extract semantic text for vector search (first 2000 chars)
        semantic_text = content[:2000] if isinstance(content, str) else content[:2000].decode("utf-8", errors="ignore")

        # 3. Save to repository (Warm Layer)
        data = {
            "name": name,
            "path": path,
            "size": file_size,
            "mime": mime,
            "content_preview": semantic_text[:500],
        }

        file_tags = list(tags or [])
        if "vfs" not in file_tags:
            file_tags.append("vfs")

        ref = await self._repo.save(
            data=data,
            table=self.TABLE,
            tags=file_tags,
            attrs={"vfs_id": file_id, "path": path}
        )

        # 4. Index in Vector Store (Hot Layer)
        self._vectors.add(
            id=ref,
            text=f"File: {name}\nPath: {path}\nContent: {semantic_text}",
            metadata={"ref": ref, "vfs_id": file_id}
        )

        return VFile(
            id=file_id,
            name=name,
            path=path,
            size=file_size,
            mime=mime,
            tags=file_tags,
            metadata=data,
            ref=ref
        )

    async def list_dir(self, path: str = "/") -> list[VFile]:
        """List files in a virtual directory."""
        rows = await self._repo.query(table=self.TABLE, where=f"attrs.path == '{path}'")
        return [self._row_to_vfile(row) for row in rows]

    async def semantic_search(self, query: str, limit: int = 5) -> list[VFile]:
        """Search for files by semantic meaning."""
        matches = self._vectors.search(query, top_k=limit)
        results = []
        for match in matches:
            ref = match.record.id
            # In a real impl, we might want to fetch full meta from repo
            # but for now we can rely on what's in the vector record or fetch
            artifact = await self._repo._port.get(ref)
            # This is a bit slow, better would be a combined query or cached metadata
            results.append(self._artifact_to_vfile(ref, artifact))
        return results

    def _row_to_vfile(self, row: MemoryRow) -> VFile:
        return VFile(
            id=row.attrs.get("vfs_id", row.ref),
            name=row.data.get("name", "unknown"),
            path=row.data.get("path", "/"),
            size=row.data.get("size", 0),
            mime=row.data.get("mime", ""),
            tags=row.tags,
            metadata=row.data,
            ref=row.ref
        )

    def _artifact_to_vfile(self, ref: str, artifact: Artifact) -> VFile:
        import json
        data = json.loads(artifact.content) if isinstance(artifact.content, str) else json.loads(artifact.content.decode("utf-8"))
        return VFile(
            id=artifact.attrs.get("vfs_id", ref),
            name=data.get("name", "unknown"),
            path=data.get("path", "/"),
            size=data.get("size", 0),
            mime=data.get("mime", ""),
            tags=list(artifact.tags),
            metadata=data,
            ref=ref
        )
