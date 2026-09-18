from __future__ import annotations

from dataclasses import dataclass

from .memory_index import MemoryIndex
from .peer_health import PeerHealthTable


@dataclass
class ReplicationPlan:
    key: str
    target_peers: list[str]
    replication_factor: int
    reason: str


class AutonomousReplicator:
    """Self-preservation layer for swarm memory.

    It selects healthy peers for memory replication and avoids peers that are
    already known replicas for the same key.
    """

    def __init__(
        self,
        memory_index: MemoryIndex,
        peer_health: PeerHealthTable,
    ) -> None:
        self.memory_index = memory_index
        self.peer_health = peer_health

    def plan_replication(
        self,
        key: str,
        replication_factor: int = 3,
    ) -> ReplicationPlan:
        existing = set(self.memory_index.peers_for([key]).keys())
        healthy = self.peer_health.healthy()

        targets: list[str] = []
        for peer in healthy:
            if peer.peer_id in existing:
                continue
            targets.append(peer.peer_id)
            if len(targets) >= replication_factor:
                break

        return ReplicationPlan(
            key=key,
            target_peers=targets,
            replication_factor=replication_factor,
            reason="replicate to healthiest non-holder peers",
        )

    def mark_replicated(self, plan: ReplicationPlan, weight: float = 1.0) -> None:
        for peer_id in plan.target_peers:
            self.memory_index.mark_replica(plan.key, peer_id, weight=weight)
