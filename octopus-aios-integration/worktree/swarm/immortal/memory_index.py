from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import time


@dataclass
class MemoryReplica:
    key: str
    peer_id: str
    ts: float = field(default_factory=time)
    weight: float = 1.0


class MemoryIndex:
    """Tracks where swarm memory/state shards are likely available.

    This lets the scheduler prefer peers that already hold relevant state,
    reducing sync cost and improving survival during partitions.
    """

    def __init__(self) -> None:
        self._replicas: dict[str, dict[str, MemoryReplica]] = defaultdict(dict)

    def mark_replica(self, key: str, peer_id: str, weight: float = 1.0) -> None:
        self._replicas[key][peer_id] = MemoryReplica(
            key=key,
            peer_id=peer_id,
            weight=weight,
        )

    def forget_peer(self, peer_id: str) -> None:
        for replicas in self._replicas.values():
            replicas.pop(peer_id, None)

    def peers_for(self, keys: list[str]) -> dict[str, float]:
        scores: dict[str, float] = defaultdict(float)
        for key in keys:
            for replica in self._replicas.get(key, {}).values():
                scores[replica.peer_id] += replica.weight
        return dict(scores)

    def export(self) -> dict[str, list[dict[str, float | str]]]:
        return {
            key: [
                {"peer_id": replica.peer_id, "weight": replica.weight, "ts": replica.ts}
                for replica in replicas.values()
            ]
            for key, replicas in self._replicas.items()
        }
