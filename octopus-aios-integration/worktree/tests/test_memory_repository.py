import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.repository import MemoryRepository


@pytest.mark.asyncio
async def test_repository_save_and_query_by_table_and_tag(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)

    await repo.save(
        {"title": "Oil change", "price": 120},
        table="orders",
        tags=["car", "service"],
    )
    await repo.save({"title": "Battery"}, table="inventory", tags=["car"])

    rows = await repo.query(table="orders", tags=["service"])
    assert len(rows) == 1
    assert rows[0].data["title"] == "Oil change"
    assert rows[0].table == "orders"


@pytest.mark.asyncio
async def test_repository_query_by_text_and_attrs(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)

    await repo.save(
        {"summary": "Best windshield supplier in town"},
        table="knowledge",
        attrs={"vendor": "bor-glass", "city": "Minsk"},
    )
    await repo.save(
        {"summary": "Another note"},
        table="knowledge",
        attrs={"vendor": "other", "city": "Minsk"},
    )

    rows = await repo.query(
        table="knowledge",
        text="windshield",
        attrs={"vendor": "bor-glass"},
    )
    assert len(rows) == 1
    assert rows[0].data["summary"].startswith("Best windshield")


@pytest.mark.asyncio
async def test_repository_query_limit(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)

    for i in range(5):
        await repo.save({"i": i}, table="events")

    rows = await repo.query(table="events", limit=2)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_repository_query_where_order_and_offset(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)

    await repo.save({"name": "A", "price": 300}, table="offers", attrs={"vendor": "x"})
    await repo.save({"name": "B", "price": 100}, table="offers", attrs={"vendor": "x"})
    await repo.save({"name": "C", "price": 200}, table="offers", attrs={"vendor": "y"})

    rows = await repo.query(
        table="offers",
        where="attrs.vendor == 'x' and data.price >= 100",
        order_by="data.price:asc",
        offset=1,
        limit=10,
    )
    assert len(rows) == 1
    assert rows[0].data["name"] == "A"
