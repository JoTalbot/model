"""Deterministic first-pass specialist selection.

The selector intentionally uses no LLM. Policy and orchestration code can depend on
stable routing before an optional learned selector is introduced later.
"""

from __future__ import annotations

from .models import AgentCandidate, SupervisorTask


class AgentSelector:
    def select(self, task: SupervisorTask) -> tuple[AgentCandidate, ...]:
        text = f"{task.title} {task.description}".lower()
        candidates: list[AgentCandidate] = []

        def add(role: str, score: float, *reasons: str) -> None:
            candidates.append(AgentCandidate(role, score, tuple(reasons)))

        add("architect", 0.8, "base architectural analysis")
        add("coder", 0.75, "implementation likely required")

        if any(x in text for x in ("bug", "error", "broken", "regression", "exception")):
            add("debugger", 0.95, "failure/debugging signal")

        if any(x in text for x in ("test", "coverage", "qa", "quality")):
            add("tester", 0.9, "testing signal")

        if any(x in text for x in ("security", "auth", "permission", "secret", "credential", "sandbox")) or task.risk_level == "high":
            add("security", 1.0, "security/risk signal")

        if any(x in text for x in ("deploy", "docker", "ci", "cd", "server", "production", "infrastructure")):
            add("devops", 0.9, "infrastructure signal")

        if any(x in text for x in ("research", "compare", "investigate", "documentation", "api")):
            add("researcher", 0.7, "research signal")

        candidates.sort(key=lambda item: (-item.score, item.role))
        limit = max(1, min(task.budget_agents, 8))
        return tuple(candidates[:limit])
