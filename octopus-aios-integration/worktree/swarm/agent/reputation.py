from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from swarm.memory.repository import MemoryRepository

logger = logging.getLogger(__name__)

TABLE_REPUTATION = "node_reputation"

@dataclass
class NodeReputation:
    node_id: str
    tasks_total: int = 0
    tasks_success: int = 0
    tasks_failed: int = 0
    last_activity: float = field(default_factory=time.time)

    @property
    def score(self) -> float:
        if self.tasks_total == 0:
            return 0.5  # Neutral score for new nodes
        return self.tasks_success / self.tasks_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "tasks_total": self.tasks_total,
            "tasks_success": self.tasks_success,
            "tasks_failed": self.tasks_failed,
            "last_activity": self.last_activity,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeReputation:
        return cls(
            node_id=data["node_id"],
            tasks_total=data.get("tasks_total", 0),
            tasks_success=data.get("tasks_success", 0),
            tasks_failed=data.get("tasks_failed", 0),
            last_activity=data.get("last_activity", time.time()),
        )


class ReputationManager:
    """Manages trust and reputation scores for peer nodes."""

    def __init__(self, repository: MemoryRepository):
        self.repo = repository
        self._cache: dict[str, NodeReputation] = {}

    async def get_reputation(self, node_id: str) -> NodeReputation:
        """Get reputation for a specific node, from cache or repository."""
        if node_id in self._cache:
            return self._cache[node_id]

        rows = await self.repo.query(
            table=TABLE_REPUTATION,
            attrs={"node_id": node_id},
            order_by="attrs._ts:desc",
            limit=1
        )
        if rows:
            rep = NodeReputation.from_dict(rows[0].data)
        else:
            rep = NodeReputation(node_id=node_id)
        
        self._cache[node_id] = rep
        return rep

    async def record_success(self, node_id: str):
        """Record a successful task completion for a node."""
        rep = await self.get_reputation(node_id)
        rep.tasks_total += 1
        rep.tasks_success += 1
        rep.last_activity = time.time()
        await self._save_reputation(rep)

    async def record_failure(self, node_id: str):
        """Record a failed task for a node."""
        rep = await self.get_reputation(node_id)
        rep.tasks_total += 1
        rep.tasks_failed += 1
        rep.last_activity = time.time()
        await self._save_reputation(rep)

    async def _save_reputation(self, rep: NodeReputation):
        """Persist reputation data."""
        await self.repo.save(
            data=rep.to_dict(),
            table=TABLE_REPUTATION,
            tags=["reputation", rep.node_id],
            attrs={"node_id": rep.node_id}
        )
        self._cache[rep.node_id] = rep

    async def list_reputation(self, limit: int = 50) -> list[NodeReputation]:
        """List current reputation for all known nodes."""
        rows = await self.repo.query(
            table=TABLE_REPUTATION,
            order_by="attrs._ts:desc",
            limit=limit * 10  # Get more to allow for history
        )
        
        seen = set()
        unique_reps = []
        for r in rows:
            rep = NodeReputation.from_dict(r.data)
            if rep.node_id not in seen:
                seen.add(rep.node_id)
                unique_reps.append(rep)
                if len(unique_reps) >= limit:
                    break
                    
        return unique_reps
