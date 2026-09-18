"""Domain-level execution state machine for AIOS vNext."""

from dataclasses import dataclass


class InvalidExecutionTransition(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionStateMachine:
    transitions: dict[str, frozenset[str]] = None

    def __post_init__(self):
        if self.transitions is None:
            object.__setattr__(self, "transitions", {
                "pending": frozenset({"running"}),
                "running": frozenset({"retrying", "completed", "failed"}),
                "retrying": frozenset({"running", "failed"}),
                "completed": frozenset(),
                "failed": frozenset({"retrying"}),
            })

    def can_transition(self, current: str, target: str) -> bool:
        return current == target or target in self.transitions.get(current, frozenset())

    def validate(self, current: str, target: str) -> None:
        if not self.can_transition(current, target):
            raise InvalidExecutionTransition(f"invalid execution transition: {current} -> {target}")
