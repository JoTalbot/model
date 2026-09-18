import pytest

from swarm.tools_runtime.execution_audit import ExecutionAudit


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
def test_transition_is_append_only_and_persistent(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = ExecutionAudit(str(path))
    audit.record_transition("e1", "node-a", "pending", "running", 0)
    audit.record_transition("e1", "node-a", "running", "retrying", 0, "temporary failure")
    audit.record_transition("e1", "node-a", "retrying", "running", 1)
    events = audit.load("e1")
    assert [e.to_status for e in events] == ["running", "retrying", "running"]
    assert events[1].reason == "temporary failure"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3
