from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

from .coordination import CoordinationSignal, CoordinationSignalKind
from .vector_clock import VectorClock


@dataclass
class AwarenessState:
    node_id: str
    clock: dict[str, int]
    signals: list[dict[str, Any]]
    ts: float = field(default_factory=time)


class AwarenessPropagation:
    """Distributed situational awareness layer.

    Local coordination signals are converted into compact awareness state that
    can be gossiped across the swarm. This lets peers share pressure, failures,
    replication gaps and partition hints without a central observer.
    """

    def __init__(self, node_id: str, clock: VectorClock) -> None:
        self.node_id = node_id
        self.clock = clock
        self.signals: list[CoordinationSignal] = []

    def observe(self, kind: CoordinationSignalKind, payload: dict[str, Any]) -> None:
        self.clock.tick()
        self.signals.append(CoordinationSignal(kind=kind, payload=payload))

    def export(self) -> AwarenessState:
        return AwarenessState(
            node_id=self.node_id,
            clock=self.clock.export(),
            signals=[
                {
                    "kind": signal.kind.value,
                    "payload": signal.payload,
                    "ts": signal.ts,
                }
                for signal in self.signals
            ],
        )

    def merge(self, state: AwarenessState) -> None:
        remote = VectorClock(node_id=self.node_id, clock=state.clock)
        self.clock.merge(remote)
        for item in state.signals:
            self.signals.append(
                CoordinationSignal(
                    kind=CoordinationSignalKind(item["kind"]),
                    payload=item["payload"],
                    ts=float(item["ts"]),
                )
            )
