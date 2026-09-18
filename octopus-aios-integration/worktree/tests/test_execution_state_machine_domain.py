import pytest

from swarm.tools_runtime.execution_state_machine import (
    ExecutionStateMachine,
    InvalidExecutionTransition,
)


def test_domain_machine_accepts_valid_transitions():
    machine = ExecutionStateMachine()
    for current, target in [("pending", "running"), ("running", "retrying"), ("retrying", "running"), ("running", "completed")]:
        machine.validate(current, target)


def test_domain_machine_rejects_invalid_transition():
    machine = ExecutionStateMachine()
    with pytest.raises(InvalidExecutionTransition):
        machine.validate("completed", "running")


def test_store_can_inject_custom_state_machine(tmp_path):
    from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore

    machine = ExecutionStateMachine({"pending": frozenset({"completed"})})
    store = ExecutionStore(str(tmp_path / "executions.json"), state_machine=machine)
    store.save(ExecutionState("e1", status="pending"))
    store.transition("e1", "completed")
    assert store.get("e1").status == "completed"
