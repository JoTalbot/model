from swarm.supervisor import (
    AgentSupervisor,
    ExecutionEngine,
    ExecutionGraphBuilder,
    SupervisorTask,
)


def test_engine_runs_dependencies_before_dependents():
    decision = AgentSupervisor().plan(
        SupervisorTask("t1", "fix auth", "Implement secure authentication", risk_level="high")
    )
    graph = ExecutionGraphBuilder().build(decision)
    seen = []
    result = ExecutionEngine(seen.append).run(graph)

    assert all(item.success for item in result)
    assert seen.index("coder") < seen.index("security")


def test_engine_fails_closed_on_executor_error():
    decision = AgentSupervisor().plan(SupervisorTask("t2", "fix bug", "Debug regression"))
    graph = ExecutionGraphBuilder().build(decision)

    def execute(role: str) -> None:
        if role == "debugger":
            raise RuntimeError("debugger unavailable")

    result = ExecutionEngine(execute).run(graph)
    failed = next(item for item in result if item.role == "debugger")
    assert failed.success is False
    assert failed.error == "debugger unavailable"


def test_engine_enforces_agent_budget():
    decision = AgentSupervisor().plan(
        SupervisorTask("t3", "deploy security bug tests", "Fix production deployment security regression", budget_agents=4)
    )
    graph = ExecutionGraphBuilder().build(decision)

    try:
        ExecutionEngine(lambda role: None, max_agents=1).run(graph)
    except ValueError as exc:
        assert "agent budget" in str(exc)
    else:
        raise AssertionError("expected agent budget failure")
