from __future__ import annotations

from dataclasses import dataclass

from .peer_health import PeerHealthTable


@dataclass
class RouteDecision:
    selected_peers: list[str]
    reason: str


class AdaptiveTopology:
    """Self-healing execution topology.

    Chooses stable peers dynamically based on health score.
    """

    def __init__(self, peer_health: PeerHealthTable) -> None:
        self.peer_health = peer_health

    def select_execution_peers(self, replicas: int = 3) -> RouteDecision:
        peers = self.peer_health.healthy(limit=replicas)

        return RouteDecision(
            selected_peers=[peer.peer_id for peer in peers],
            reason="health-weighted peer selection",
        )
