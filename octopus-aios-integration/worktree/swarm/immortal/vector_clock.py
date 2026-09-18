from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VectorClock:
    """Causal clock for distributed swarm state.

    It tracks per-node logical time and lets the immortal runtime distinguish:
    - happened-before updates
    - happened-after updates
    - concurrent branches
    - equal clocks
    """

    node_id: str
    clock: dict[str, int] = field(default_factory=dict)

    def tick(self) -> "VectorClock":
        self.clock[self.node_id] = self.clock.get(self.node_id, 0) + 1
        return self

    def merge(self, other: "VectorClock") -> "VectorClock":
        for node, value in other.clock.items():
            self.clock[node] = max(self.clock.get(node, 0), value)
        return self

    def copy(self) -> "VectorClock":
        return VectorClock(node_id=self.node_id, clock=dict(self.clock))

    def compare(self, other: "VectorClock") -> str:
        """Compare two clocks.

        Returns one of:
        - "before"
        - "after"
        - "equal"
        - "concurrent"
        """

        nodes = set(self.clock) | set(other.clock)
        less = False
        greater = False

        for node in nodes:
            left = self.clock.get(node, 0)
            right = other.clock.get(node, 0)
            if left < right:
                less = True
            elif left > right:
                greater = True

        if less and greater:
            return "concurrent"
        if less:
            return "before"
        if greater:
            return "after"
        return "equal"

    def export(self) -> dict[str, int]:
        return dict(self.clock)
