"""Helpers for atomic execution checkpoint updates during recovery."""

from .execution_store import ExecutionState, ExecutionStore


class RecoveryCheckpoint:
    def __init__(self, store: ExecutionStore):
        self.store = store

    def mark_running(self, state: ExecutionState, attempt: int, plan=None):
        state.status = "running"
        state.attempt = attempt
        if plan is not None:
            state.plan = plan
        return self.store.save(state)

    def mark_completed(self, state: ExecutionState, result=None):
        state.status = "completed"
        state.result = result
        state.error = None
        return self.store.save(state)

    def mark_failed(self, state: ExecutionState, error):
        state.status = "failed"
        state.error = str(error)
        return self.store.save(state)
