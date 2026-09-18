"""Dependency-free execution graph for bounded specialist plans."""

from __future__ import annotations

from dataclasses import dataclass

from .models import SupervisorDecision


@dataclass(frozen=True)
class ExecutionNode:
    role: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionGraph:
    nodes: tuple[ExecutionNode, ...]
    parallel_groups: tuple[tuple[str, ...], ...]


class ExecutionGraphBuilder:
    """Build a stable graph without executing agents."""

    def build(self, decision: SupervisorDecision) -> ExecutionGraph:
        roles = tuple(candidate.role for candidate in decision.selected)
        nodes: list[ExecutionNode] = []
        for role in roles:
            dependencies: tuple[str, ...] = ()
            if role == "reviewer" or role == "tester":
                dependencies = tuple(r for r in roles if r == "coder")
            elif role == "security":
                dependencies = tuple(r for r in roles if r in {"coder", "architect"})
            nodes.append(ExecutionNode(role, dependencies))

        independent = tuple(node.role for node in nodes if not node.depends_on)
        dependent = tuple(node.role for node in nodes if node.depends_on)
        groups = tuple(group for group in (independent, dependent) if group)
        return ExecutionGraph(tuple(nodes), groups)
