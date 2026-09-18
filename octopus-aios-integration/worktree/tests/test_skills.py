from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm.agent.skills import ChatSkill, MemoryDbSkill, WebParserSkill


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Extracted price: 5000 RUB")
    return llm


@pytest.fixture
def mock_memory():
    memory = AsyncMock()
    memory.store = AsyncMock(return_value="block-1")
    return memory


@pytest.mark.asyncio
async def test_web_parser_skill(mock_llm):
    """WebParserSkill.execute delegates to the pipeline then falls back to legacy."""
    skill = WebParserSkill(llm=mock_llm)
    mock_response = AsyncMock()
    mock_response.text = "<html><body><p>Price: 5000</p></body></html>"
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    # The pipeline's fetcher uses httpx at `swarm.parser.fetcher.httpx` and
    # the legacy fallback uses `swarm.agent.skills.httpx`.  We patch both.
    with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockPipeClient, \
         patch("swarm.agent.skills.httpx.AsyncClient") as MockLegacyClient:

        # Pipeline fetcher mock (will fetch the page, but LLM returns non-JSON
        # so pipeline yields 0 items and the skill falls back to legacy).
        pipe_inst = AsyncMock()
        pipe_inst.get = AsyncMock(return_value=mock_response)
        MockPipeClient.return_value.__aenter__ = AsyncMock(return_value=pipe_inst)
        MockPipeClient.return_value.__aexit__ = AsyncMock(return_value=None)

        # Legacy client mock
        leg_inst = AsyncMock()
        leg_inst.get = AsyncMock(return_value=mock_response)
        leg_inst.aclose = AsyncMock()
        MockLegacyClient.return_value.__aenter__ = AsyncMock(return_value=leg_inst)
        MockLegacyClient.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await skill.execute(
            url="https://example.com",
            instruction="Extract the price",
        )

    assert "5000" in result
    # LLM called twice: once by the pipeline extractor (got non-JSON back),
    # once by the legacy fallback (returned the final text).
    assert mock_llm.complete.call_count == 2


@pytest.mark.asyncio
async def test_web_parser_skill_pipeline_success():
    """When the pipeline returns items, the skill returns JSON without fallback."""
    import json
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "items": [{"name": "Glass", "price": "5000", "currency": "RUB"}]
    }))

    skill = WebParserSkill(llm=llm)
    mock_response = AsyncMock()
    mock_response.text = "<html><body><p>Glass 5000 RUB</p></body></html>"
    mock_response.status_code = 200

    with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
        mock_inst = AsyncMock()
        mock_inst.get = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await skill.execute(
            url="https://shop.com",
            instruction="Extract items",
        )

    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "Glass"
    # Only called once — pipeline succeeded, no legacy fallback
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_web_parser_skill_search():
    """search_and_parse uses the pipeline in search mode."""
    import json
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "items": [{"name": "Part", "price": "100"}]
    }))

    skill = WebParserSkill(llm=llm)

    with patch("swarm.parser.resolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve, \
         patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:

        mock_resolve.return_value = ["https://found.com"]

        mock_resp = AsyncMock()
        mock_resp.text = "<html><body>Part 100</body></html>"
        mock_resp.status_code = 200
        mock_inst = AsyncMock()
        mock_inst.get = AsyncMock(return_value=mock_resp)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await skill.search_and_parse("autoglass lada", limit=2)

    assert "Part" in result
    assert "100" in result


@pytest.mark.asyncio
async def test_chat_skill_send(mock_llm, mock_memory):
    rpc = AsyncMock()
    rpc.call = AsyncMock(return_value={"status": "ok"})

    skill = ChatSkill(llm=mock_llm, memory=mock_memory, rpc_client=rpc, node_id="agent-1")
    response = await skill.send_message(
        target_node="agent-2",
        target_port=8001,
        message="Hello, how are you?",
        context="We are discussing autoglass prices",
    )
    assert response is not None
    rpc.call.assert_called_once()


@pytest.mark.asyncio
async def test_chat_skill_saves_dialog(mock_llm, mock_memory):
    rpc = AsyncMock()
    rpc.call = AsyncMock(return_value={"status": "ok"})

    skill = ChatSkill(llm=mock_llm, memory=mock_memory, rpc_client=rpc, node_id="agent-1")
    await skill.send_message(
        target_node="agent-2",
        target_port=8001,
        message="Test message",
        context="Test context",
    )
    mock_memory.store.assert_called_once()


@pytest.mark.asyncio
async def test_chat_skill_uses_memory_port(mock_llm, mock_memory):
    rpc = AsyncMock()
    rpc.call = AsyncMock(return_value={"status": "ok"})
    port = AsyncMock()
    port.put = AsyncMock(return_value="ref:swarm:block-1")

    skill = ChatSkill(
        llm=mock_llm,
        memory=mock_memory,
        rpc_client=rpc,
        node_id="agent-1",
        memory_port=port,
    )
    await skill.send_message(
        target_node="agent-2",
        target_port=8001,
        message="Test message",
        context="Test context",
    )
    port.put.assert_awaited_once()
    mock_memory.store.assert_not_called()


@pytest.mark.asyncio
async def test_memory_db_skill_save_and_query(tmp_path):
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.repository import MemoryRepository

    repo = MemoryRepository(CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)}))
    skill = MemoryDbSkill(repository=repo)

    ref = await skill.save_record(
        table="knowledge",
        data={"summary": "Best windshield supplier"},
        tags=["auto"],
        attrs={"vendor": "bor-glass"},
    )
    assert ref.startswith("ref:file:")

    rows = await skill.query_records(
        table="knowledge",
        tags=["auto"],
        text="windshield",
        attrs={"vendor": "bor-glass"},
        limit=10,
    )
    assert len(rows) == 1
    assert rows[0].data["summary"].startswith("Best windshield")


@pytest.mark.asyncio
async def test_memory_db_skill_query_where_order_offset(tmp_path):
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.repository import MemoryRepository

    repo = MemoryRepository(CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)}))
    skill = MemoryDbSkill(repository=repo)
    await skill.save_record(table="offers", data={"name": "A", "price": 300}, attrs={"vendor": "x"})
    await skill.save_record(table="offers", data={"name": "B", "price": 100}, attrs={"vendor": "x"})

    rows = await skill.query_records(
        table="offers",
        where="attrs.vendor == 'x' and data.price >= 100",
        order_by="data.price:asc",
        offset=1,
        limit=5,
    )
    assert len(rows) == 1
    assert rows[0].data["name"] == "A"
