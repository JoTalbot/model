import asyncio
from swarm.memory.vfs import VirtualFileSystem
from swarm.memory.vector_store import VectorStore, HashingEmbedder
from swarm.memory.repository import MemoryRepository
from swarm.agent.linker import MemoryLinker
from swarm.memory.graph_rag import GraphRAG

class MockMemoryPort:
    def __init__(self): self.storage = {}
    async def put(self, art): ref = f"mock:{len(self.storage)}"; self.storage[ref] = art; return ref
    async def get(self, ref): return self.storage.get(ref)
    async def exists(self, ref): return ref in self.storage
    async def search(self, tags, owner=None):
        from swarm.memory.types import RefMeta
        return [RefMeta(ref=r, scheme="mock", tags=a.tags) for r, a in self.storage.items() if any(t in a.tags for t in tags)]

async def test_links():
    port = MockMemoryPort()
    repo = MemoryRepository(port)
    vectors = VectorStore(HashingEmbedder())
    vfs = VirtualFileSystem(repo, vectors)
    linker = MemoryLinker(repo, vectors)
    graph_rag = GraphRAG(repo, vectors)

    # 1. Store two related files
    print("Storing AI docs...")
    f1 = await vfs.store_file("ai_core.txt", "Artificial Intelligence is the core of Gemaxi.", "/notes")
    f2 = await vfs.store_file("swarm.txt", "Gemaxi uses a swarm of agents based on Artificial Intelligence.", "/notes")
    
    # 2. Link them
    print("Linking memories...")
    await linker.link_item(f1.ref)
    await linker.link_item(f2.ref)
    
    # 3. Graph RAG check
    print("\nRetrieving context for 'What is Gemaxi?':")
    context = await graph_rag.retrieve_context("What is Gemaxi?", top_k=1)
    print(context)

if __name__ == "__main__":
    asyncio.run(test_links())
