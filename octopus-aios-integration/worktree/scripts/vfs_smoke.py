import asyncio
import unittest
from swarm.memory.vfs import VirtualFileSystem
from swarm.memory.vector_store import VectorStore
from swarm.memory.repository import MemoryRepository
from swarm.memory.types import Artifact

class MockMemoryPort:
    def __init__(self):
        self.storage = {}

    async def put(self, artifact):
        ref = f"mock:{len(self.storage)}"
        self.storage[ref] = artifact
        return ref

    async def get(self, ref):
        return self.storage.get(ref)

    async def search(self, tags, owner=None):
        from swarm.memory.types import RefMeta
        return [RefMeta(ref=r, scheme="mock", tags=a.tags) for r, a in self.storage.items() if any(t in a.tags for t in tags)]

async def test_vfs():
    port = MockMemoryPort()
    repo = MemoryRepository(port)
    vectors = VectorStore()
    vfs = VirtualFileSystem(repo, vectors)

    # 1. Store a file
    print("Storing file...")
    vfile = await vfs.store_file(
        name="hello.txt",
        content="Hello world, this is a test file for Gemaxi VFS.",
        path="/docs",
        tags=["test", "documentation"]
    )
    print(f"Stored: {vfile.id} at {vfile.ref}")

    # 2. List directory
    print("\nListing /docs:")
    files = await vfs.list_dir("/docs")
    for f in files:
        print(f"- {f.name} ({f.size} bytes)")

    # 3. Semantic search
    print("\nSearching for 'documentation':")
    results = await vfs.semantic_search("documentation about gemaxi")
    for f in results:
        print(f"Match: {f.name} path={f.path} ref={f.ref}")

if __name__ == "__main__":
    asyncio.run(test_vfs())
