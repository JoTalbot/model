"""Top-level policy-free supervisor for dynamic specialist routing."""

from __future__ import annotations

from .models import SupervisorDecision, SupervisorTask
from .selector import AgentSelector


class AgentSupervisor:
    """Choose a bounded team without executing agents itself."""

    def __init__(self, selector: AgentSelector | None = None) -> None:
        self._selector = selector or AgentSelector()

    def plan(self, task: SupervisorTask) -> SupervisorDecision:
        selected = self._selector.select(task)
        if not selected:
            return SupervisorDecision((), parallel=False, reason="no specialist matched")

        roles = {candidate.role for candidate in selected}
        parallel = len(roles) > 1
        reason = "; ".join(
            f"{candidate.role}: {', '.join(candidate.reasons) or 'score'}"
            for candidate in selected
        )
        return SupervisorDecision(
            selected=selected,
            parallel=parallel,
            reason=reason,
            estimated_agents=len(selected),
        )
