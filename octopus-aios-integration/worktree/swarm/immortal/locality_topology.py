from __future__ import annotations

from dataclasses import dataclass

from .memory_index import MemoryIndex
from .peer_health import PeerHealthTable


@dataclass
class LocalityRoute:
    selected_peers: list[str]
    memory_scores: dict[str, float]


class LocalityAwareTopology:
    """Topology engine that prefers peers close to relevant memory."""

    def __init__(
        self,
        peer_health: PeerHealthTable,
        memory_index: MemoryIndex,
    ) -> None:
        self.peer_health = peer_health
        self.memory_index = memory_index

    def select_peers(
        self,
        memory_keys: list[str],
        replicas: int = 3,
    ) -> LocalityRoute:
        locality_scores = self.memory_index.peers_for(memory_keys)

        healthy = {
            peer.peer_id: peer.score
            for peer in self.peer_health.healthy()
        }

        combined = []

        for peer_id, health_score in healthy.items():
            locality_score = locality_scores.get(peer_id, 0.0)
            combined_score = health_score + locality_score
            combined.append((combined_score, peer_id))

        combined.sort(reverse=True)

        selected = [peer_id for _, peer_id in combined[:replicas]]

        return LocalityRoute(
            selected_peers=selected,
            memory_scores=locality_scores,
        )
