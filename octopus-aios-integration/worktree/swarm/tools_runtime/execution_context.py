"""Shared execution context and correlation identity for AIOS vNext."""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ExecutionContext:
    execution_id: str = field(default_factory=lambda: uuid4().hex)
    agent_id: str = ""
    goal: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    events: list = field(default_factory=list)

    def add_event(self, event: Any):
        self.events.append(event)

    def child(self, **metadata: Any) -> "ExecutionContext":
        merged = dict(self.metadata)
        merged.update(metadata)
        return ExecutionContext(
            agent_id=self.agent_id,
            goal=self.goal,
            metadata=merged,
            parent_id=self.execution_id,
        )
