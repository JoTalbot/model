"""Startup recovery for restart-safe AIOS executions."""

from typing import Any

from .execution_store import ExecutionState, ExecutionStore


class RecoveryManager:
    """Discover resumable executions and hand them back to the runtime."""

    def __init__(self, store: ExecutionStore):
        self.store = store

    def pending(self):
        return self.store.resumable()

    async def recover(self, loop, agent: Any, context: dict | None = None):
        recovered = []
        for state in self.pending():
            result = await loop.resume(state.execution_id, agent, context=context)
            recovered.append((state.execution_id, result))
        return recovered

    def mark_failed(self, state: ExecutionState, error: BaseException):
        state.status = "failed"
        state.error = str(error)
        return self.store.save(state)
