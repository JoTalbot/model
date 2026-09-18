from swarm.supervisor import (
    AgentSupervisor,
    ConflictResolver,
    ExecutionGraphBuilder,
    SpecialistOpinion,
    SupervisorTask,
)


def test_security_graph_depends_on_implementation():
    decision = AgentSupervisor().plan(
        SupervisorTask("t1", "fix auth", "Implement secure authentication", risk_level="high")
    )
    graph = ExecutionGraphBuilder().build(decision)
    security = next(node for node in graph.nodes if node.role == "security")
    assert "coder" in security.depends_on


def test_conflict_resolver_prefers_evidence_weighted_winner():
    result = ConflictResolver().resolve(
        (
            SpecialistOpinion("reviewer", "APPROVED", 0.9, ("tests pass",)),
            SpecialistOpinion("security", "APPROVED", 0.8, ("policy pass",)),
            SpecialistOpinion("tester", "CHANGES_REQUESTED", 0.2, ("minor issue",)),
        )
    )
    assert result.resolved is True
    assert result.decision == "APPROVED"


def test_conflict_resolver_fails_closed_on_equal_conflict():
    result = ConflictResolver().resolve(
        (
            SpecialistOpinion("reviewer", "APPROVED", 1.0),
            SpecialistOpinion("security", "CHANGES_REQUESTED", 1.0),
        )
    )
    assert result.resolved is False
    assert result.decision == "UNRESOLVED"
