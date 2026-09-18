import asyncio
import pytest
import json
from swarm.agent.linker import MemoryLinker
from swarm.memory.repository import MemoryRepository
from swarm.memory.vector_store import VectorStore, HashingEmbedder
from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.types import Artifact

class MockLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        return json.dumps({
            "type": "SIMILAR",
            "explanation": "These two items discuss distributed AI systems."
        })

@pytest.fixture
async def repo(tmp_path):
    adapter = LocalScratchAdapter(str(tmp_path))
    port = CompositeMemoryPort({"file": adapter})
    return MemoryRepository(port)

@pytest.mark.asyncio
async def test_advanced_linker(repo):
    store = VectorStore(HashingEmbedder(dims=256))
    llm = MockLLM()
    linker = MemoryLinker(repo, store, llm=llm)
    
    # 1. Add two identical items to guarantee high similarity
    text = "Distributed swarm agents using Python."
    ref1 = await repo.save(data={"text": text}, table="vfs_files")
    store.add(id=ref1, text=text)
    
    ref2 = await repo.save(data={"text": text}, table="vfs_files")
    store.add(id=ref2, text=text)
    
    # 2. Link item 1
    await linker.link_item(ref1, threshold=0.1)
    
    # 3. Verify - the updated item should be in the repository
    # Since repo.save creates new records, we query for the latest one in the table
    rows = await repo.query(table="vfs_files", order_by="attrs._ts:desc")
    
    # Find the one that has semantic_edges
    updated_item = next((r for r in rows if "semantic_edges" in r.attrs), None)
    
    assert updated_item is not None
    edge = updated_item.attrs["semantic_edges"][0]
    assert edge["relation_type"] == "SIMILAR"
    assert "distributed AI" in edge["explanation"]
    assert llm.calls > 0
