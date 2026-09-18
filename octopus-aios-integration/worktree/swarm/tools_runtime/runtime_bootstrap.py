"""Startup orchestration for restart-safe AIOS runtime recovery."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .execution_commit import ExecutionCommitCoordinator
from .execution_lease import ExecutionLeaseStore
from .execution_store import ExecutionStore
from .recovery_manager import RecoveryManager
from .recovery_policy import RecoveryAction, RecoveryPolicy
from .recovery_queue import RecoveryQueue, RecoveryQueueItem


@dataclass(frozen=True)
class RecoveryReport:
    discovered: int
    attempted: int
    recovered: int
    failed: int
    skipped: int = 0
    reconciled: int = 0
    reconciliation_failed: int = 0
    retried: int = 0
    quarantined: int = 0
    manual_review: int = 0


class RuntimeBootstrap:
    def __init__(self, store: ExecutionStore | None = None, recovery_manager: RecoveryManager | None = None,
                 lease_store: ExecutionLeaseStore | None = None, owner_id: str = "aios-runtime",
                 heartbeat_interval: float | None = None, commit_coordinator: ExecutionCommitCoordinator | None = None,
                 recovery_policy: RecoveryPolicy | None = None, recovery_queue: RecoveryQueue | None = None):
        self.store = store or ExecutionStore()
        self.recovery_manager = recovery_manager or RecoveryManager(self.store)
        self.lease_store = lease_store or ExecutionLeaseStore()
        self.owner_id = owner_id
        ttl = self.lease_store.ttl_seconds
        self.heartbeat_interval = heartbeat_interval if heartbeat_interval is not None else max(0.1, ttl / 3)
        self.commit_coordinator = commit_coordinator
        self.recovery_policy = recovery_policy or RecoveryPolicy()
        self.recovery_queue = recovery_queue or RecoveryQueue()

    async def _heartbeat(self, execution_id: str):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            if self.lease_store.renew(execution_id, self.owner_id) is None:
                raise RuntimeError(f"execution lease lost: {execution_id}")

    def _reconcile(self):
        if self.commit_coordinator is None:
            return 0, 0
        try:
            return len(self.commit_coordinator.reconcile()), 0
        except Exception:
            return 0, 1

    async def recover_pending(self, resume: Callable[[Any], Awaitable[Any]]) -> RecoveryReport:
        reconciled, reconciliation_failed = self._reconcile()
        pending = self.store.resumable()
        recovered = failed = skipped = retried = quarantined = manual_review = 0
        for state in pending:
            decision = self.recovery_policy.decide(state.execution_id, state.status, state.attempt)
            if decision.action is RecoveryAction.SKIP:
                skipped += 1
                continue
            if decision.action in {RecoveryAction.QUARANTINE, RecoveryAction.MANUAL_REVIEW}:
                self.recovery_queue.enqueue(RecoveryQueueItem(state.execution_id, decision.action.value, decision.reason, state.attempt, getattr(state, "correlation_id", None)))
                if decision.action is RecoveryAction.QUARANTINE:
                    quarantined += 1
                else:
                    manual_review += 1
                continue
            retried += 1
            lease = self.lease_store.acquire(state.execution_id, self.owner_id)
            if lease is None:
                skipped += 1
                continue
            heartbeat = asyncio.create_task(self._heartbeat(state.execution_id))
            try:
                await resume(state)
                recovered += 1
            except Exception as exc:
                failed += 1
                if hasattr(self.recovery_manager, "mark_failed"):
                    self.recovery_manager.mark_failed(state, exc)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                self.lease_store.release(state.execution_id, self.owner_id)
        return RecoveryReport(len(pending), retried, recovered, failed, skipped, reconciled, reconciliation_failed, retried, quarantined, manual_review)

    async def recover_with_loop(self, loop, agent: Any, context: dict | None = None) -> RecoveryReport:
        return await self.recover_pending(lambda state: loop.resume(state.execution_id, agent, context=context))
