import asyncio
import pytest
from swarm.agent.core import Task, SwarmAgent, TaskStatus
from swarm.agent.reputation import ReputationManager
from swarm.memory.repository import MemoryRepository
from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort

class MockLLM:
    async def complete(self, messages):
        return "mock result"

@pytest.fixture
async def repo(tmp_path):
    adapter = LocalScratchAdapter(str(tmp_path))
    port = CompositeMemoryPort({"file": adapter})
    return MemoryRepository(port)

@pytest.mark.asyncio
async def test_reputation_manager(repo):
    rm = ReputationManager(repo)
    
    node_id = "node-1"
    
    # Check default
    rep = await rm.get_reputation(node_id)
    assert rep.node_id == node_id
    assert rep.score == 0.5
    
    # Record success
    await rm.record_success(node_id)
    rep = await rm.get_reputation(node_id)
    assert rep.tasks_total == 1
    assert rep.tasks_success == 1
    assert rep.score == 1.0
    
    # Record failure
    await rm.record_failure(node_id)
    rep = await rm.get_reputation(node_id)
    assert rep.tasks_total == 2
    assert rep.tasks_success == 1
    assert rep.score == 0.5
    
    # List
    reps = await rm.list_reputation()
    assert len(reps) == 1
    assert reps[0].node_id == node_id

@pytest.mark.asyncio
async def test_reputation_blocking(repo):
    # This is more of an integration test logic check
    rm = ReputationManager(repo)
    node_id = "bad-node"
    
    # Make it bad
    for _ in range(10):
        await rm.record_failure(node_id)
        
    rep = await rm.get_reputation(node_id)
    assert rep.score == 0.0
    
    # Logic check: would we refuse a claim?
    # (Checking the logic we implemented in runtime.py)
    is_blocked = rep.score < 0.2 and rep.tasks_total > 5
    assert is_blocked is True
