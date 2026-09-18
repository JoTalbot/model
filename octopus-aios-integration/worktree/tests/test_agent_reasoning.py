"""Тесты для swarm.agent.reasoning, executor, archivist, linker."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.agent.archivist import Archivist
from swarm.agent.executor import TaskExecutor
from swarm.agent.linker import MemoryLinker
from swarm.agent.reasoning import ReasoningEngine

# ── ReasoningEngine ───────────────────────────────────────────────────────


class TestReasoningEngine:
    @pytest.mark.asyncio
    async def test_think_basic(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="answer")
        engine = ReasoningEngine(llm)
        result = await engine.think("question")
        assert result == "answer"
        llm.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_think_with_system_prompt(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="ok")
        engine = ReasoningEngine(llm)
        await engine.think("q", system_prompt="you are helpful")
        msgs = llm.complete.call_args[0][0]
        assert msgs[0]["role"] == "system"
        assert "helpful" in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_think_with_graph_rag(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="enriched answer")
        graph_rag = AsyncMock()
        graph_rag.retrieve_context = AsyncMock(return_value="knowledge from graph")

        engine = ReasoningEngine(llm, graph_rag=graph_rag)
        result = await engine.think("query", use_graph=True)
        assert result == "enriched answer"
        # Контекст должен содержать данные из graph_rag
        sent = llm.complete.call_args[0][0][-1]["content"]
        assert "knowledge from graph" in sent

    @pytest.mark.asyncio
    async def test_think_graph_disabled(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="plain")
        graph_rag = AsyncMock()

        engine = ReasoningEngine(llm, graph_rag=graph_rag)
        await engine.think("q", use_graph=False)
        graph_rag.retrieve_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_think_graph_returns_none(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="fallback")
        graph_rag = AsyncMock()
        graph_rag.retrieve_context = AsyncMock(return_value=None)

        engine = ReasoningEngine(llm, graph_rag=graph_rag)
        result = await engine.think("q")
        assert result == "fallback"


# ── TaskExecutor ──────────────────────────────────────────────────────────


class TestTaskExecutor:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="task result")
        memory = AsyncMock()
        memory.store = AsyncMock(return_value="block-id")
        reasoning = ReasoningEngine(llm)
        bus = AsyncMock()
        bus.publish = AsyncMock()

        executor = TaskExecutor("node-1", memory, reasoning, bus=bus)

        from swarm.agent.core import Task
        task = Task(description="do something", creator_id="node-1")
        await executor.execute(task)

        assert task.result == "task result"
        assert task.status.value == "done"
        bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        memory = AsyncMock()
        reasoning = ReasoningEngine(llm)
        bus = AsyncMock()
        bus.publish = AsyncMock()

        executor = TaskExecutor("node-1", memory, reasoning, bus=bus)

        from swarm.agent.core import Task
        task = Task(description="fail task", creator_id="node-1")
        await executor.execute(task)

        assert task.status.value == "failed"
        bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_memory_port(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="result via port")
        memory = AsyncMock()
        port = AsyncMock()
        port.put = AsyncMock(return_value="ref:file:xyz")
        reasoning = ReasoningEngine(llm)

        executor = TaskExecutor("node-1", memory, reasoning, memory_port=port)

        from swarm.agent.core import Task
        task = Task(description="port task", creator_id="node-1")
        await executor.execute(task)

        port.put.assert_called_once()


# ── Archivist ─────────────────────────────────────────────────────────────


class TestArchivist:
    @pytest.mark.asyncio
    async def test_consolidate_archives_important(self, tmp_path):
        from swarm.memory.adapters.local_scratch import LocalScratchAdapter
        from swarm.memory.composite import CompositeMemoryPort
        from swarm.memory.immortal import ImmortalMemoryManager, IPFSProvider
        from swarm.memory.repository import MemoryRepository
        from swarm.memory.vector_store import VectorStore

        port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
        repo = MemoryRepository(port)
        ipfs = IPFSProvider(simulate=True)
        mgr = ImmortalMemoryManager(VectorStore(), repo, ipfs, provider_name="ipfs")

        # Создаём записи: одна важная, одна нет
        await repo.save(data={"size": 50000}, table="vfs_files",
                        tags=["important"], attrs={"importance": 0.9})
        await repo.save(data={"size": 100}, table="vfs_files",
                        tags=["trivial"])

        archivist = Archivist(mgr, repo)
        count = await archivist.consolidate(tables=["vfs_files"])  # updated: kwarg renamed table->tables
        assert count >= 1

    def test_calculate_importance(self):
        archivist = Archivist(MagicMock(), MagicMock())
        row = MagicMock()
        row.data = {"size": 50000}
        row.tags = ["important"]
        score = archivist._calculate_importance(row)
        assert score > 0.8

    def test_calculate_importance_low(self):
        archivist = Archivist(MagicMock(), MagicMock())
        row = MagicMock()
        row.data = {"size": 100}
        row.tags = []
        score = archivist._calculate_importance(row)
        assert score <= 0.8


# ── MemoryLinker ──────────────────────────────────────────────────────────


class TestMemoryLinker:
    @pytest.mark.asyncio
    async def test_link_item_no_matches(self, tmp_path):
        from swarm.memory.adapters.local_scratch import LocalScratchAdapter
        from swarm.memory.composite import CompositeMemoryPort
        from swarm.memory.repository import MemoryRepository
        from swarm.memory.vector_store import HashingEmbedder, VectorStore

        port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
        repo = MemoryRepository(port)
        vs = VectorStore(HashingEmbedder())

        ref = await repo.save(data={"text": "lonely item"}, table="t")
        linker = MemoryLinker(repo, vs)
        links = await linker.link_item(ref)
        assert links == []

    @pytest.mark.asyncio
    async def test_link_nonexistent_ref(self, tmp_path):
        from swarm.memory.adapters.local_scratch import LocalScratchAdapter
        from swarm.memory.composite import CompositeMemoryPort
        from swarm.memory.repository import MemoryRepository
        from swarm.memory.types import RefNotFoundError
        from swarm.memory.vector_store import VectorStore

        port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
        repo = MemoryRepository(port)
        vs = VectorStore()

        linker = MemoryLinker(repo, vs)
        # Несуществующий ref → RefNotFoundError (или пустой список)
        try:
            links = await linker.link_item("ref:file:nonexistent")
            assert links == []
        except RefNotFoundError:
            pass  # Тоже допустимо
