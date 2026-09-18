from swarm.supervisor import ExecutionResult
from swarm.supervisor.result_aggregator import ResultAggregator


def test_aggregator_approves_successful_execution():
    results = (ExecutionResult("coder", True), ExecutionResult("tester", True))
    decision = ResultAggregator().aggregate(results)
    assert decision.decision == "APPROVE"
    assert decision.resolved is True


def test_aggregator_retries_failed_specialist():
    results = (ExecutionResult("coder", True), ExecutionResult("tester", False, "tests failed"))
    decision = ResultAggregator().aggregate(results)
    assert decision.decision == "RETRY"
    assert decision.resolved is False
    assert decision.failed_roles == ("tester",)


def test_aggregator_blocks_without_results():
    decision = ResultAggregator().aggregate(())
    assert decision.decision == "BLOCK"
    assert decision.resolved is False
