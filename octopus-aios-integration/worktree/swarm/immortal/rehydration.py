from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RehydrationSnapshot:
    head: str | None
    state: dict[str, Any]
    peers: list[str]


class Rehydrator:
    """Restores node runtime state from distributed snapshots."""

    def restore(self, snapshot: RehydrationSnapshot) -> dict[str, Any]:
        return {
            "restored": True,
            "head": snapshot.head,
            "peer_count": len(snapshot.peers),
            "state": snapshot.state,
        }
