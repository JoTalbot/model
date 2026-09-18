"""Persistent operator queues for quarantine and manual recovery decisions."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class RecoveryQueueItem:
    execution_id: str
    action: str
    reason: str
    attempt: int
    correlation_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resolved: bool = False


class RecoveryQueue:
    def __init__(self, path: str = "data/recovery_queue.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self):
        if not self.path.exists():
            return []
        return [RecoveryQueueItem(**json.loads(line)) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _rewrite(self, items):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text("".join(json.dumps(asdict(item), ensure_ascii=False) + "\n" for item in items), encoding="utf-8")
        tmp.replace(self.path)

    def enqueue(self, item: RecoveryQueueItem) -> RecoveryQueueItem:
        items = self._read()
        if any(x.execution_id == item.execution_id and x.action == item.action and not x.resolved for x in items):
            return item
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
        return item

    def resolve(self, execution_id: str, action: str) -> bool:
        items = self._read()
        changed = False
        updated = []
        for item in items:
            if item.execution_id == execution_id and item.action == action and not item.resolved:
                item = RecoveryQueueItem(item.execution_id, item.action, item.reason, item.attempt, item.correlation_id, item.created_at, True)
                changed = True
            updated.append(item)
        if changed:
            self._rewrite(updated)
        return changed

    def items(self, action: str | None = None, unresolved_only: bool = False):
        result = self._read()
        return [item for item in result if (action is None or item.action == action) and (not unresolved_only or not item.resolved)]
