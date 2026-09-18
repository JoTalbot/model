"""Тесты для swarm.business.autoglass — каталог, VIN-декодер, прайсы."""

import pytest

from swarm.business.autoglass import (
    GlassCatalog,
    GlassItem,
    decode_vin,
)

# ── VIN Decoder ────────────────────────────────────────────────────────────


class TestDecodeVin:
    def test_lada_vin(self):
        info = decode_vin("XTA219070R0000001")
        assert info.valid is True
        assert info.make == "Lada"
        assert info.country == "Россия"
        assert info.year == 2024  # R = 2024

    def test_bmw_vin(self):
        info = decode_vin("WBA5B31070GP12345")
        assert info.valid is True
        assert info.make == "BMW"
        assert info.country == "Германия"

    def test_mercedes_vin(self):
        info = decode_vin("WDB1234567F890123")
        assert info.valid is True
        assert info.make == "Mercedes-Benz"

    def test_toyota_vin(self):
        info = decode_vin("JTDKARFU5J3123456")
        assert info.valid is True
        assert info.make == "Toyota"
        assert info.year == 2018  # J = 2018

    def test_hyundai_vin(self):
        info = decode_vin("KMHD35LH5HU123456")
        assert info.valid is True
        assert info.make == "Hyundai"

    def test_kia_vin(self):
        info = decode_vin("KNAFU411BG5123456")
        assert info.valid is True
        assert info.make == "Kia"

    def test_tesla_vin(self):
        info = decode_vin("5YJ3E1EA1NF123456")
        assert info.valid is True
        assert info.make == "Tesla"
        assert info.year == 2022  # N = 2022

    def test_unknown_wmi(self):
        info = decode_vin("ZZZ12345678901234")
        assert info.valid is True
        assert info.make is None  # Неизвестный WMI

    def test_invalid_vin_too_short(self):
        info = decode_vin("XTA2190")
        assert info.valid is False
        assert info.error == "invalid_vin_format"

    def test_invalid_vin_bad_chars(self):
        info = decode_vin("XTA219070I0000001")  # I запрещена в VIN
        assert info.valid is False

    def test_empty_vin(self):
        info = decode_vin("")
        assert info.valid is False

    def test_vin_case_insensitive(self):
        info = decode_vin("xta219070r0000001")
        assert info.valid is True
        assert info.make == "Lada"

    def test_vin_with_spaces(self):
        info = decode_vin("  WBA5B31070GP12345  ")
        assert info.valid is True
        assert info.make == "BMW"

    def test_vin_info_to_dict(self):
        info = decode_vin("XTA219070R0000001")
        d = info.to_dict()
        assert d["vin"] == "XTA219070R0000001"
        assert d["make"] == "Lada"
        assert d["valid"] is True


# ── GlassItem ──────────────────────────────────────────────────────────────


class TestGlassItem:
    def test_to_dict(self):
        item = GlassItem(
            name="Лобовое Lada Granta",
            glass_type="лобовое",
            makes=["Lada"],
            models=["Granta"],
            years=[2020, 2021],
            oem_code="21190-5206010",
            price=5500.0,
            supplier="БОР",
        )
        d = item.to_dict()
        assert d["name"] == "Лобовое Lada Granta"
        assert d["glass_type"] == "лобовое"
        assert d["makes"] == ["Lada"]
        assert d["years"] == [2020, 2021]
        assert d["price"] == 5500.0

    def test_from_dict(self):
        d = {
            "name": "Test Glass",
            "glass_type": "боковое",
            "makes": ["BMW"],
            "price": 12000,
        }
        item = GlassItem.from_dict(d)
        assert item.name == "Test Glass"
        assert item.glass_type == "боковое"
        assert item.makes == ["BMW"]
        assert item.price == 12000.0

    def test_from_dict_defaults(self):
        item = GlassItem.from_dict({})
        assert item.name == ""
        assert item.makes == []
        assert item.price == 0.0
        assert item.in_stock is True

    def test_roundtrip(self):
        item = GlassItem(
            name="A",
            glass_type="заднее",
            makes=["Toyota"],
            models=["Camry"],
            years=[2019],
            price=8000,
        )
        d = item.to_dict()
        item2 = GlassItem.from_dict(d)
        assert item2.name == item.name
        assert item2.glass_type == item.glass_type
        assert item2.years == item.years


# ── GlassCatalog ───────────────────────────────────────────────────────────


@pytest.fixture
def catalog(tmp_path):
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.repository import MemoryRepository

    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)
    return GlassCatalog(repo)


class TestGlassCatalog:
    @pytest.mark.asyncio
    async def test_add_and_list(self, catalog):
        item = GlassItem(name="Glass A", price=5000, makes=["Lada"], glass_type="лобовое")
        ref = await catalog.add(item)
        assert ref.startswith("ref:file:")

        items = await catalog.list_all()
        assert len(items) == 1
        assert items[0].name == "Glass A"

    @pytest.mark.asyncio
    async def test_count(self, catalog):
        assert await catalog.count() == 0
        await catalog.add(GlassItem(name="A", price=100))
        await catalog.add(GlassItem(name="B", price=200))
        assert await catalog.count() == 2

    @pytest.mark.asyncio
    async def test_search_by_make(self, catalog):
        await catalog.add(GlassItem(name="Lada Glass", makes=["Lada"], price=5000))
        await catalog.add(GlassItem(name="BMW Glass", makes=["BMW"], price=15000))

        results = await catalog.search(make="Lada")
        assert len(results) == 1
        assert results[0].name == "Lada Glass"

    @pytest.mark.asyncio
    async def test_search_by_type(self, catalog):
        await catalog.add(GlassItem(name="Front", glass_type="лобовое", price=5000))
        await catalog.add(GlassItem(name="Side", glass_type="боковое", price=2000))

        results = await catalog.search(glass_type="лобовое")
        assert len(results) == 1
        assert results[0].name == "Front"

    @pytest.mark.asyncio
    async def test_search_by_model(self, catalog):
        await catalog.add(GlassItem(name="A", makes=["Lada"], models=["Granta"], price=1))
        await catalog.add(GlassItem(name="B", makes=["Lada"], models=["Vesta"], price=2))

        results = await catalog.search(make="Lada", model="Granta")
        assert len(results) == 1
        assert results[0].name == "A"

    @pytest.mark.asyncio
    async def test_search_in_stock_filter(self, catalog):
        await catalog.add(GlassItem(name="Stock", in_stock=True, price=1))
        await catalog.add(GlassItem(name="NoStock", in_stock=False, price=2))

        results = await catalog.search(in_stock=True)
        assert len(results) == 1
        assert results[0].name == "Stock"

    @pytest.mark.asyncio
    async def test_search_text(self, catalog):
        await catalog.add(GlassItem(name="Лобовое для Granta", price=5000))
        await catalog.add(GlassItem(name="Боковое для Camry", price=8000))

        results = await catalog.search(text="Granta")
        assert len(results) == 1
        assert "Granta" in results[0].name

    @pytest.mark.asyncio
    async def test_search_by_vin(self, catalog):
        await catalog.add(GlassItem(
            name="Лобовое Lada Granta",
            makes=["Lada"],
            models=["Granta"],
            years=[2024],
            price=5500,
        ))
        await catalog.add(GlassItem(
            name="BMW Windshield",
            makes=["BMW"],
            price=20000,
        ))

        # XTA = Lada, R = 2024
        info, items = await catalog.search_by_vin("XTA219070R0000001")
        assert info.make == "Lada"
        assert len(items) == 1
        assert items[0].name == "Лобовое Lada Granta"

    @pytest.mark.asyncio
    async def test_search_by_vin_invalid(self, catalog):
        info, items = await catalog.search_by_vin("INVALID")
        assert info.valid is False
        assert items == []

    @pytest.mark.asyncio
    async def test_search_by_vin_unknown_make(self, catalog):
        info, items = await catalog.search_by_vin("ZZZ12345678901234")
        assert info.valid is True
        assert info.make is None
        assert items == []

    @pytest.mark.asyncio
    async def test_search_by_vin_year_filter(self, catalog):
        await catalog.add(GlassItem(
            name="Old Glass",
            makes=["Lada"],
            years=[2015, 2016],
            price=3000,
        ))
        await catalog.add(GlassItem(
            name="New Glass",
            makes=["Lada"],
            years=[2023, 2024],
            price=5000,
        ))

        _info, items = await catalog.search_by_vin("XTA219070R0000001")  # R=2024
        assert len(items) == 1
        assert items[0].name == "New Glass"

    @pytest.mark.asyncio
    async def test_price_snapshot(self, catalog):
        ref = await catalog.add_price_snapshot(
            source_url="https://competitor.com/parts",
            items=[
                {"name": "Glass X", "price": "4500", "currency": "RUB"},
                {"name": "Glass Y", "price": "6000", "currency": "RUB"},
            ],
            query="лобовое стекло lada",
        )
        assert ref.startswith("ref:file:")

        history = await catalog.price_history()
        assert len(history) == 1
        assert history[0]["source_url"] == "https://competitor.com/parts"
        assert len(history[0]["items"]) == 2

    @pytest.mark.asyncio
    async def test_price_history_empty(self, catalog):
        history = await catalog.price_history()
        assert history == []

    @pytest.mark.asyncio
    async def test_multiple_price_snapshots(self, catalog):
        await catalog.add_price_snapshot(
            source_url="https://a.com",
            items=[{"name": "A", "price": "100"}],
        )
        await catalog.add_price_snapshot(
            source_url="https://b.com",
            items=[{"name": "B", "price": "200"}],
        )

        history = await catalog.price_history()
        assert len(history) == 2
