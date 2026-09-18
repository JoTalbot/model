"""Persistent execution state backed by a domain state machine and audit log."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .execution_audit import ExecutionAuditEvent, ExecutionAuditLog
from .execution_state_machine import ExecutionStateMachine


@dataclass
class ExecutionState:
    execution_id: str
    status: str = "pending"
    goal: str = ""
    attempt: int = 0
    plan: Any = None
    result: Any = None
    error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    correlation_id: str | None = None


class ExecutionStore:
    """Small atomic JSON store delegating lifecycle rules to the domain machine."""

    def __init__(self, path: str = "data/executions.json", state_machine: ExecutionStateMachine | None = None, audit_log: ExecutionAuditLog | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_machine = state_machine or ExecutionStateMachine()
        self.audit_log = audit_log
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def save(self, state: ExecutionState) -> ExecutionState:
        data = self._read()
        previous = data.get(state.execution_id)
        if previous:
            self.state_machine.validate(previous.get("status", "pending"), state.status)
        old_status = previous.get("status", "pending") if previous else None
        state.updated_at = datetime.now(UTC).isoformat()
        data[state.execution_id] = asdict(state)
        self._write(data)
        if self.audit_log and old_status != state.status:
            self.audit_log.append(ExecutionAuditEvent(state.execution_id, old_status or "new", state.status, state.attempt, state.error, correlation_id=state.correlation_id))
        return state

    def transition(self, execution_id: str, status: str, **updates) -> ExecutionState:
        state = self.get(execution_id)
        if not state:
            if status != "pending":
                raise KeyError(execution_id)
            state = ExecutionState(execution_id=execution_id)
        self.state_machine.validate(state.status, status)
        state.status = status
        for key, value in updates.items():
            setattr(state, key, value)
        return self.save(state)

    def get(self, execution_id: str) -> ExecutionState | None:
        raw = self._read().get(execution_id)
        return ExecutionState(**raw) if raw else None

    def resumable(self):
        return [ExecutionState(**raw) for raw in self._read().values() if raw.get("status") in {"running", "retrying"}]
