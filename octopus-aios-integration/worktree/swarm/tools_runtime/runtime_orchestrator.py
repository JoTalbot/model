"""Unified lifecycle API for the AIOS vNext runtime."""

from dataclasses import dataclass
from typing import Any

from .execution_audit import ExecutionAuditLog
from .execution_commit import ExecutionCommitCoordinator
from .execution_lease import ExecutionLeaseStore
from .execution_store import ExecutionStore
from .recovery_manager import RecoveryManager
from .runtime_bootstrap import RecoveryReport, RuntimeBootstrap
from .runtime_factory import build_execution_loop
from .shutdown_manager import ShutdownManager


@dataclass
class RuntimeComponents:
    store: ExecutionStore
    lease_store: ExecutionLeaseStore
    recovery_manager: RecoveryManager
    bootstrap: RuntimeBootstrap
    loop: Any
    shutdown_manager: ShutdownManager
    commit_coordinator: ExecutionCommitCoordinator


class RuntimeOrchestrator:
    def __init__(self, executor, planner, *, owner_id="aios-runtime", store=None, lease_store=None, policy=None, event_bus=None,
                 audit_log=None, commit_coordinator=None):
        self.store = store or ExecutionStore()
        self.lease_store = lease_store or ExecutionLeaseStore()
        self.audit_log = audit_log or ExecutionAuditLog()
        self.commit_coordinator = commit_coordinator or ExecutionCommitCoordinator(self.store, self.audit_log)
        self.recovery_manager = RecoveryManager(self.store)
        self.bootstrap = RuntimeBootstrap(store=self.store, recovery_manager=self.recovery_manager,
                                          lease_store=self.lease_store, owner_id=owner_id,
                                          commit_coordinator=self.commit_coordinator)
        self.loop = build_execution_loop(executor, planner, owner_id=owner_id, store=self.store,
                                         lease_store=self.lease_store, policy=policy, event_bus=event_bus)
        self.shutdown_manager = ShutdownManager()
        self.shutdown_manager.register_release(self._release_owned_leases)
        self.owner_id = owner_id
        self.started = False

    @property
    def components(self) -> RuntimeComponents:
        return RuntimeComponents(self.store, self.lease_store, self.recovery_manager, self.bootstrap, self.loop, self.shutdown_manager, self.commit_coordinator)

    async def start(self, agent: Any, context: dict | None = None) -> RecoveryReport:
        if self.started:
            return RecoveryReport(0, 0, 0, 0, 0)
        try:
            report = await self.bootstrap.recover_with_loop(self.loop, agent, context=context)
            self.started = True
            return report
        except Exception:
            self.started = False
            raise

    async def execute(self, goal: str, agent: Any, context: dict | None = None):
        if not self.started:
            await self.start(agent, context=context)
        return await self.loop.run(goal, agent, context=context)

    async def _release_owned_leases(self):
        for state in self.store.resumable():
            self.lease_store.release(state.execution_id, self.owner_id)

    async def shutdown(self):
        result = await self.shutdown_manager.shutdown()
        self.started = False
        return result
