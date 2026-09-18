"""Bounded execution engine for validated specialist graphs.

The engine accepts an injected executor and executes dependency-safe batches.
Independent roles in the same batch run concurrently, while failures stop later
batches. Graph validation is fail-closed before any executor is called.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .execution_graph import ExecutionGraph
from .graph_validator import ExecutionGraphValidator


@dataclass(frozen=True)
class ExecutionResult:
    role: str
    success: bool
    error: str | None = None


class ExecutionEngine:
    """Execute a validated graph in bounded dependency-safe parallel batches."""

    def __init__(
        self,
        executor: Callable[[str], object],
        max_agents: int = 8,
        validator: ExecutionGraphValidator | None = None,
    ) -> None:
        if max_agents < 1:
            raise ValueError("max_agents must be >= 1")
        self._executor = executor
        self._max_agents = max_agents
        self._validator = validator or ExecutionGraphValidator()

    def run(self, graph: ExecutionGraph) -> tuple[ExecutionResult, ...]:
        if len(graph.nodes) > self._max_agents:
            raise ValueError("execution graph exceeds agent budget")

        validation = self._validator.validate(graph)
        if not validation.valid:
            raise ValueError(validation.reason)

        nodes = {node.role: node for node in graph.nodes}
        completed: set[str] = set()
        results: list[ExecutionResult] = []
        remaining = set(nodes)

        while remaining:
            ready = sorted(
                role for role in remaining
                if set(nodes[role].depends_on).issubset(completed)
            )
            if not ready:
                raise ValueError("execution graph contains unresolved dependencies or a cycle")

            batch_results: dict[str, ExecutionResult] = {}
            with ThreadPoolExecutor(max_workers=min(len(ready), self._max_agents)) as pool:
                futures = {pool.submit(self._executor, role): role for role in ready}
                for future in as_completed(futures):
                    role = futures[future]
                    try:
                        future.result()
                        batch_results[role] = ExecutionResult(role, True)
                    except Exception as exc:  # noqa: BLE001 — aggregator must survive any agent failure
                        batch_results[role] = ExecutionResult(role, False, str(exc))

            for role in ready:
                result = batch_results[role]
                results.append(result)
                if not result.success:
                    return tuple(results)
                completed.add(role)
                remaining.remove(role)

        return tuple(results)
