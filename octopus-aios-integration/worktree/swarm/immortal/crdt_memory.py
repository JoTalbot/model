from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(order=True)
class LwwValue:
    """Last-write-wins register value.

    This is a small CRDT primitive. It is not the final swarm memory model,
    but it gives the immortal layer deterministic conflict resolution.
    """

    ts: float
    node_id: str
    value: Any = field(compare=False)


class LwwMap:
    """Mergeable key-value map using last-write-wins semantics."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self._data: dict[str, LwwValue] = {}

    def set(self, key: str, value: Any, ts: float | None = None) -> None:
        self._data[key] = LwwValue(ts=ts or time(), node_id=self.node_id, value=value)

    def get(self, key: str, default: Any = None) -> Any:
        item = self._data.get(key)
        return item.value if item else default

    def merge(self, other: "LwwMap") -> None:
        for key, incoming in other._data.items():
            current = self._data.get(key)
            if current is None or incoming > current:
                self._data[key] = incoming

    def export(self) -> dict[str, dict[str, Any]]:
        return {
            key: {"ts": item.ts, "node_id": item.node_id, "value": item.value}
            for key, item in self._data.items()
        }

    @classmethod
    def import_from(cls, node_id: str, payload: dict[str, dict[str, Any]]) -> "LwwMap":
        obj = cls(node_id=node_id)
        for key, item in payload.items():
            obj._data[key] = LwwValue(
                ts=float(item["ts"]),
                node_id=str(item["node_id"]),
                value=item["value"],
            )
        return obj
