"""Checkpoint adapter that refuses stale execution owners."""

from .recovery_checkpoint import RecoveryCheckpoint


class LeaseAwareCheckpoint:
    def __init__(self, checkpoint: RecoveryCheckpoint, lease_store, owner_id: str):
        self.checkpoint = checkpoint
        self.lease_store = lease_store
        self.owner_id = owner_id

    def _assert_owner(self, execution_id: str):
        if not self.lease_store.is_owner(execution_id, self.owner_id):
            raise RuntimeError(f"execution '{execution_id}' lease is not owned by '{self.owner_id}'")

    def mark_running(self, state, attempt, plan=None):
        self._assert_owner(state.execution_id)
        return self.checkpoint.mark_running(state, attempt, plan)

    def mark_completed(self, state, result=None):
        self._assert_owner(state.execution_id)
        return self.checkpoint.mark_completed(state, result)

    def mark_failed(self, state, error):
        self._assert_owner(state.execution_id)
        return self.checkpoint.mark_failed(state, error)
