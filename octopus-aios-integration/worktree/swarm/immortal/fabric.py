from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .carrier import CarrierRegistry, CarrierKind
from .crdt_memory import LwwMap
from .ghost_executor import GhostExecutor
from .identity import SwarmIdentity
from .memory_index import MemoryIndex
from .peer_health import PeerHealthTable
from .portable_runtime import PortableRuntime
from .replication import AutonomousReplicator, ReplicationPlan
from .scheduler import CognitiveScheduler, ScheduledExecution
from .snapshot import ConsciousnessSnapshot, SnapshotManager
from .timeline import TemporalLog
from .topology import AdaptiveTopology
from .verifier import MajorityVerifier
from .vector_clock import VectorClock


@dataclass
class FabricStatus:
    swarm_id: str
    identity_fingerprint: str
    peers: int
    carriers: int
    timeline_head: str | None
    vector_clock: dict[str, int]


class ConsciousnessFabric:
    """Unified immortal swarm runtime facade.

    This object connects identity, memory, topology, scheduling, execution,
    temporal persistence and snapshot continuity into one substrate.
    """

    def __init__(self, swarm_id: str, node_id: str) -> None:
        self.identity = SwarmIdentity(swarm_id=swarm_id)
        self.clock = VectorClock(node_id=node_id)
        self.memory = LwwMap(node_id=node_id)
        self.memory_index = MemoryIndex()
        self.peer_health = PeerHealthTable()
        self.carriers = CarrierRegistry()
        self.portable_runtime = PortableRuntime(self.carriers)
        self.temporal_log = TemporalLog()
        self.snapshot_manager = SnapshotManager()

        self.topology = AdaptiveTopology(self.peer_health)
        self.executor = GhostExecutor()
        self.verifier = MajorityVerifier()
        self.scheduler = CognitiveScheduler(self.topology, self.executor, self.verifier)
        self.replicator = AutonomousReplicator(self.memory_index, self.peer_health)

    def register_peer(self, peer_id: str) -> None:
        self.peer_health.touch(peer_id)
        self.temporal_log.append("peer.registered", {"peer_id": peer_id})

    def register_carrier(
        self,
        carrier_id: str,
        kind: CarrierKind = CarrierKind.UNKNOWN,
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        self.carriers.register(carrier_id, kind=kind, capabilities=capabilities)
        self.temporal_log.append(
            "carrier.registered",
            {"carrier_id": carrier_id, "kind": kind.value},
        )

    def remember(self, key: str, value: Any) -> None:
        self.clock.tick()
        self.memory.set(key, value)
        self.memory_index.mark_replica(key, self.clock.node_id)
        self.temporal_log.append(
            "memory.updated",
            {"key": key, "clock": self.clock.export()},
        )

    def plan_replication(self, key: str, factor: int = 3) -> ReplicationPlan:
        plan = self.replicator.plan_replication(key, replication_factor=factor)
        self.temporal_log.append(
            "memory.replication_planned",
            {"key": key, "targets": plan.target_peers},
        )
        return plan

    async def execute(self, task, replicas: int = 3) -> ScheduledExecution:
        result = await self.scheduler.execute(task=task, replicas=replicas)
        self.temporal_log.append(
            "execution.completed",
            {"peers": result.peers, "accepted": result.accepted},
        )
        return result

    def snapshot(self) -> ConsciousnessSnapshot:
        return self.snapshot_manager.create_snapshot(
            state=self.memory.export(),
            vector_clock=self.clock.export(),
            memory_index=self.memory_index.export(),
            peer_health={
                peer_id: {
                    "score": peer.score,
                    "last_seen": peer.last_seen,
                    "failures": peer.failures,
                    "successes": peer.successes,
                }
                for peer_id, peer in self.peer_health.peers.items()
            },
        )

    def status(self) -> FabricStatus:
        return FabricStatus(
            swarm_id=self.identity.swarm_id,
            identity_fingerprint=self.identity.fingerprint(),
            peers=len(self.peer_health.peers),
            carriers=len(self.carriers.carriers),
            timeline_head=self.temporal_log.head,
            vector_clock=self.clock.export(),
        )
