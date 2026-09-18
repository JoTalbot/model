from __future__ import annotations

from dataclasses import dataclass, field
from time import time


@dataclass
class PeerHealth:
    peer_id: str
    score: float = 1.0
    last_seen: float = field(default_factory=time)
    failures: int = 0
    successes: int = 0

    def mark_success(self) -> None:
        self.successes += 1
        self.last_seen = time()
        self.score = min(1.0, self.score + 0.05)

    def mark_failure(self) -> None:
        self.failures += 1
        self.score = max(0.0, self.score - 0.15)

    @property
    def alive(self) -> bool:
        return self.score > 0.2


class PeerHealthTable:
    """Health-aware peer registry for self-healing topology."""

    def __init__(self) -> None:
        self.peers: dict[str, PeerHealth] = {}

    def touch(self, peer_id: str) -> PeerHealth:
        peer = self.peers.setdefault(peer_id, PeerHealth(peer_id=peer_id))
        peer.last_seen = time()
        return peer

    def success(self, peer_id: str) -> None:
        self.touch(peer_id).mark_success()

    def failure(self, peer_id: str) -> None:
        self.touch(peer_id).mark_failure()

    def healthy(self, limit: int | None = None) -> list[PeerHealth]:
        items = sorted(
            [peer for peer in self.peers.values() if peer.alive],
            key=lambda peer: peer.score,
            reverse=True,
        )
        return items[:limit] if limit else items
