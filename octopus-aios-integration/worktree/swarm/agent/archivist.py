from __future__ import annotations

import logging
from typing import Any

from swarm.memory.immortal import ImmortalMemoryManager
from swarm.memory.repository import MemoryRepository

logger = logging.getLogger(__name__)

class Archivist:
    """Agent that manages the long-term lifecycle of memories."""

    def __init__(self, memory_manager: ImmortalMemoryManager, repository: MemoryRepository):
        self.manager = memory_manager
        self.repo = repository

    async def consolidate(self, tables: list[str] | None = None):
        """Scan active records across multiple tables and archive the important ones."""
        if tables is None:
            tables = ["vfs_files", "notes", "files"]
            
        archived_count = 0
        for table in tables:
            try:
                rows = await self.repo.query(table=table)
                for row in rows:
                    # Skip if already archived
                    if "cold_id" in row.attrs:
                        continue

                    importance = self._calculate_importance(row)

                    if importance > 0.8:
                        logger.info("Archiving important record from %s: %s (importance: %.2f)", table, row.ref, importance)
                        record = await self.manager.archive(row.ref, importance=importance)
                        if record:
                            archived_count += 1
            except Exception as e:
                logger.error("Error consolidating table %s: %s", table, e)

        return archived_count

    def _calculate_importance(self, row: Any) -> float:
        score = 0.5
        
        # Tags influence importance
        tags = row.tags or []
        if "important" in tags or "permanent" in tags or "life" in tags:
            score += 0.4
            
        # Larger records might be more valuable
        if isinstance(row.data, dict):
            size = row.data.get("size", 0)
            if not size and "content" in row.data:
                size = len(str(row.data["content"]))
            if size > 5000:
                score += 0.1
                
        # Project related
        if any(t.startswith("project:") for t in tags):
            score += 0.1

        return min(1.0, score)
