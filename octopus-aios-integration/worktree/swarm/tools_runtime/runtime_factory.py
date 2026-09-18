"""Factory for constructing a lease-aware autonomous runtime."""

from .autonomous_loop import AutonomousExecutionLoop
from .execution_lease import ExecutionLeaseStore
from .execution_store import ExecutionStore
from .lease_aware_checkpoint import LeaseAwareCheckpoint
from .recovery_checkpoint import RecoveryCheckpoint


def build_execution_loop(executor, planner, *, owner_id="aios-runtime", store=None, lease_store=None, policy=None, event_bus=None):
    store = store or ExecutionStore()
    lease_store = lease_store or ExecutionLeaseStore()
    checkpoint = LeaseAwareCheckpoint(RecoveryCheckpoint(store), lease_store, owner_id)
    return AutonomousExecutionLoop(
        executor,
        planner,
        policy=policy,
        event_bus=event_bus,
        store=store,
        checkpoint=checkpoint,
    )
