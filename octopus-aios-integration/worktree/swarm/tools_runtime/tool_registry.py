"""Policy-aware tool registry for AIOS vNext."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: Callable[..., Any]
    permissions: set[str] = field(default_factory=set)


class ToolPermissionError(PermissionError):
    pass


class ToolRegistry:
    """Register and invoke tools through an explicit permission boundary."""

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, handler: Callable[..., Any], permissions: Iterable[str] | None = None):
        if not name or not callable(handler):
            raise ValueError("tool name and callable handler are required")
        self._tools[name] = ToolSpec(name, handler, set(permissions or ()))

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    async def execute(self, name: str, *, granted_permissions: Iterable[str] | None = None, **kwargs):
        spec = self.get(name)
        granted = set(granted_permissions or ())
        missing = spec.permissions - granted
        if missing:
            raise ToolPermissionError(f"tool '{name}' requires permissions: {sorted(missing)}")
        result = spec.handler(**kwargs)
        if hasattr(result, "__await__"):
            return await result
        return result

    def names(self):
        return tuple(sorted(self._tools))
