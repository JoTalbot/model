from swarm.supervisor import AgentSupervisor, SupervisorTask


def test_security_task_selects_security_specialist():
    decision = AgentSupervisor().plan(
        SupervisorTask("t1", "auth permissions", "Review authentication and secret handling", risk_level="high")
    )
    roles = {candidate.role for candidate in decision.selected}
    assert "security" in roles
    assert decision.estimated_agents <= 4


def test_debug_task_selects_debugger():
    decision = AgentSupervisor().plan(
        SupervisorTask("t2", "fix regression", "Debug failing API tests")
    )
    assert decision.selected[0].role == "debugger"


def test_budget_bounds_team_size():
    decision = AgentSupervisor().plan(
        SupervisorTask("t3", "deploy security bug tests", "Fix production deployment security regression", budget_agents=2)
    )
    assert len(decision.selected) == 2
    assert decision.estimated_agents == 2
