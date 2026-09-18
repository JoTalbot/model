from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from swarm.memory.repository import MemoryRepository, MemoryRow

logger = logging.getLogger(__name__)

@dataclass
class Snapshot:
    timestamp: float
    items: list[MemoryRow]

class TimeMachine:
    """Manages temporal views of the Gemaxi memory."""

    def __init__(self, repository: MemoryRepository):
        self.repo = repository

    async def get_snapshot_at(self, target_ts: float) -> Snapshot:
        """Returns the state of memory as it was at target_ts."""
        # Query all records
        all_rows = await self.repo.query(limit=100000)

        # Filter rows that were created BEFORE or AT target_ts
        # We assume _ts attribute exists in metadata
        past_rows = [
            row for row in all_rows
            if row.attrs.get("_ts", 0) <= target_ts
        ]

        return Snapshot(timestamp=target_ts, items=past_rows)

    async def list_history(self, ref: str) -> list[dict[str, Any]]:
        """List version history of a specific memory item."""
        # This requires a 'versioning' system where we keep old rows or tags.
        # In Gemaxi, we can look for items with the same 'vfs_id' or 'id'.
        artifact = await self.repo._port.get(ref)
        if not artifact:
            return []

        vfs_id = artifact.attrs.get("vfs_id")
        if not vfs_id:
            return [{"ref": ref, "ts": artifact.attrs.get("_ts", 0)}]

        rows = await self.repo.query(where=f"attrs.vfs_id == '{vfs_id}'")
        rows.sort(key=lambda r: r.attrs.get("_ts", 0))

        return [
            {"ref": r.ref, "ts": r.attrs.get("_ts", 0), "tags": r.tags}
            for r in rows
        ]
