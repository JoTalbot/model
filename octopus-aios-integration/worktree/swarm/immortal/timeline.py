from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from time import time
from typing import Any


@dataclass
class TimelineEvent:
    kind: str
    payload: dict[str, Any]
    ts: float = field(default_factory=time)
    parent: str | None = None

    @property
    def event_id(self) -> str:
        raw = f"{self.parent}:{self.ts}:{self.kind}:{repr(self.payload)}".encode()
        return sha256(raw).hexdigest()


class TemporalLog:
    """Append-only history for swarm continuity.

    The state DAG answers: what is true now?
    The temporal log answers: how did the swarm become this?
    """

    def __init__(self) -> None:
        self.events: dict[str, TimelineEvent] = {}
        self.head: str | None = None

    def append(self, kind: str, payload: dict[str, Any]) -> str:
        event = TimelineEvent(kind=kind, payload=payload, parent=self.head)
        event_id = event.event_id
        self.events[event_id] = event
        self.head = event_id
        return event_id

    def replay(self) -> list[TimelineEvent]:
        ordered: list[TimelineEvent] = []
        cursor = self.head
        while cursor:
            event = self.events[cursor]
            ordered.append(event)
            cursor = event.parent
        return list(reversed(ordered))

    def export(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "events": {
                event_id: {
                    "kind": event.kind,
                    "payload": event.payload,
                    "ts": event.ts,
                    "parent": event.parent,
                }
                for event_id, event in self.events.items()
            },
        }
