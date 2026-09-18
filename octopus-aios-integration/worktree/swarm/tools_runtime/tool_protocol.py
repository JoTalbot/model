"""Typed protocol objects for AIOS tool execution."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    timeout: float | None = None


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool: str
    ok: bool
    value: Any = None
    error: str | None = None
    retryable: bool = False

    @classmethod
    def success(cls, call: ToolCall, value: Any):
        return cls(call.call_id, call.tool, True, value=value)

    @classmethod
    def failure(cls, call: ToolCall, error: BaseException, *, retryable: bool = False):
        return cls(call.call_id, call.tool, False, error=str(error), retryable=retryable)
