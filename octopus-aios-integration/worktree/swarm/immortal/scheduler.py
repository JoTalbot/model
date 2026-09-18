from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Any

from .ghost_executor import GhostExecutor
from .topology import AdaptiveTopology
from .verifier import MajorityVerifier


@dataclass
class ScheduledExecution:
    peers: list[str]
    accepted: bool
    result: dict[str, Any]


class CognitiveScheduler:
    """Distributed execution planner.

    Future versions can:
    - prioritize peers geographically
    - optimize latency
    - route memory-aware tasks
    - run speculative execution
    """

    def __init__(
        self,
        topology: AdaptiveTopology,
        executor: GhostExecutor,
        verifier: MajorityVerifier,
    ) -> None:
        self.topology = topology
        self.executor = executor
        self.verifier = verifier

    async def execute(
        self,
        task: Callable[[], Awaitable[Any]],
        replicas: int = 3,
    ) -> ScheduledExecution:
        route = self.topology.select_execution_peers(replicas=replicas)

        results = await self.executor.execute(
            workers=route.selected_peers,
            task=task,
        )

        verification = self.verifier.verify(results)

        return ScheduledExecution(
            peers=route.selected_peers,
            accepted=verification.get("accepted", False),
            result=verification,
        )
