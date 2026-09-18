"""Validation for bounded specialist execution graphs."""

from __future__ import annotations

from dataclasses import dataclass

from .execution_graph import ExecutionGraph


@dataclass(frozen=True)
class GraphValidation:
    valid: bool
    reason: str


class ExecutionGraphValidator:
    """Fail closed on missing dependencies, duplicate roles, or cycles."""

    def validate(self, graph: ExecutionGraph) -> GraphValidation:
        roles = [node.role for node in graph.nodes]
        if len(roles) != len(set(roles)):
            return GraphValidation(False, "duplicate execution node role")

        known = set(roles)
        for node in graph.nodes:
            missing = [dep for dep in node.depends_on if dep not in known]
            if missing:
                return GraphValidation(False, f"missing dependencies for {node.role}: {', '.join(sorted(missing))}")

        state: dict[str, int] = {role: 0 for role in roles}
        dependencies = {node.role: node.depends_on for node in graph.nodes}

        def visit(role: str) -> bool:
            if state[role] == 1:
                return False
            if state[role] == 2:
                return True
            state[role] = 1
            for dependency in dependencies[role]:
                if not visit(dependency):
                    return False
            state[role] = 2
            return True

        if any(not visit(role) for role in roles):
            return GraphValidation(False, "execution graph contains a dependency cycle")
        return GraphValidation(True, "execution graph valid")
