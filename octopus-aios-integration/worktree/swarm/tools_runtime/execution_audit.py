"""Structured and persistent audit trail for vNext execution lifecycle."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .execution_context import ExecutionContext
from .execution_events import ExecutionEvent


@dataclass(frozen=True)
class ExecutionAuditEvent:
    execution_id: str
    from_status: str
    to_status: str
    attempt: int = 0
    reason: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_id: str = ""
    correlation_id: str | None = None

    def with_identity(self):
        if self.event_id:
            return self
        payload = f"{self.execution_id}|{self.from_status}|{self.to_status}|{self.attempt}|{self.reason}|{self.timestamp}|{self.correlation_id}"
        return ExecutionAuditEvent(**{**asdict(self), "event_id": hashlib.sha256(payload.encode()).hexdigest()})


@dataclass
class AuditEvent:
    event: str
    agent_id: str
    tool: str | None = None
    status: str = "ok"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    execution_id: str | None = None
    correlation_id: str | None = None


class ExecutionAuditLog:
    def __init__(self, path: str = "data/execution_audit.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: ExecutionAuditEvent) -> ExecutionAuditEvent:
        event = event.with_identity()
        if self._contains(event.event_id):
            return event
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    def _contains(self, event_id: str) -> bool:
        if not self.path.exists():
            return False
        return any(json.loads(line).get("event_id") == event_id for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())

    def events(self, execution_id: str | None = None):
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = ExecutionAuditEvent(**json.loads(line))
                if execution_id is None or event.execution_id == execution_id:
                    result.append(event)
        return result


class ExecutionAudit:
    def __init__(self):
        self.events: list[AuditEvent] = []

    def record(self, event: str, agent_id: str, tool: str | None = None, status: str = "ok", context: ExecutionContext | None = None, correlation_id: str | None = None, **metadata):
        item = AuditEvent(event, agent_id, tool, status, metadata, execution_id=getattr(context, "execution_id", None), correlation_id=correlation_id)
        self.events.append(item)
        return item

    def record_event(self, event: ExecutionEvent):
        return self.record(event.type, event.context.agent_id, context=event.context, **event.data)

    def snapshot(self):
        return list(self.events)
