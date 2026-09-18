"""Correlated runtime events used by audit, memory and reflection layers."""

from dataclasses import dataclass, field
from typing import Any

from .execution_context import ExecutionContext


@dataclass(frozen=True)
class ExecutionEvent:
    type: str
    context: ExecutionContext
    data: dict[str, Any] = field(default_factory=dict)
