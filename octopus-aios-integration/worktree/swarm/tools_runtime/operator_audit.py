"""Durable, typed audit trail for operator recovery actions."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class OperatorAuditAction(StrEnum):
    RESOLVE = "resolve"
    RETRY = "retry"
    QUARANTINE = "quarantine"
    MANUAL_REVIEW = "manual_review"


class OperatorAuditOutcome(StrEnum):
    RESOLVED = "resolved"
    FAILED = "failed"


@dataclass(frozen=True)
class OperatorAuditEvent:
    action: str
    execution_id: str
    actor: str
    outcome: str
    reason: str | None = None
    correlation_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class OperatorAuditLog:
    def __init__(self, path: str = "data/operator_audit.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: OperatorAuditEvent):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    def events(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
