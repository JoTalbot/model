from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from time import time
from typing import Any


@dataclass
class StatePatch:
    key: str
    value: Any
    ts: float = field(default_factory=time)


@dataclass
class StateCommit:
    parent: str | None
    patch: StatePatch
    ts: float = field(default_factory=time)

    @property
    def hash(self) -> str:
        payload = f"{self.parent}:{self.patch.key}:{self.patch.ts}".encode()
        return sha256(payload).hexdigest()


class StateDag:
    """Append-only DAG-like state timeline.

    First minimal implementation for immortal swarm runtime.
    Later this can be upgraded to CRDT merge + distributed persistence.
    """

    def __init__(self) -> None:
        self.commits: dict[str, StateCommit] = {}
        self.head: str | None = None
        self.materialized: dict[str, Any] = {}

    def commit(self, patch: StatePatch) -> str:
        commit = StateCommit(parent=self.head, patch=patch)
        self.commits[commit.hash] = commit
        self.materialized[patch.key] = patch.value
        self.head = commit.hash
        return commit.hash

    def snapshot(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "state": dict(self.materialized),
            "commit_count": len(self.commits),
        }
