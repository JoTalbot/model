from swarm.tools_runtime.recovery_policy import RecoveryAction, RecoveryPolicy


def test_retry_respects_attempt_limit():
    policy = RecoveryPolicy(max_attempts=3)
    assert policy.decide("e1", "running", 0).action is RecoveryAction.RETRY
    assert policy.decide("e1", "running", 3).action is RecoveryAction.MANUAL_REVIEW


def test_corrupt_journal_is_quarantined():
    decision = RecoveryPolicy().decide("e1", "running", 0, journal_corrupt=True)
    assert decision.action is RecoveryAction.QUARANTINE


def test_non_resumable_execution_is_skipped():
    decision = RecoveryPolicy().decide("e1", "completed", 0)
    assert decision.action is RecoveryAction.SKIP
