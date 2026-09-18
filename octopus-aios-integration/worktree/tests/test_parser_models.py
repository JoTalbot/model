"""Tests for swarm.parser.models."""


from swarm.parser.models import ParsedItem, ParseResult


class TestParsedItem:
    def test_to_dict_full(self):
        item = ParsedItem(
            name="Windshield Lada Granta",
            price="5000",
            currency="RUB",
            shop="AutoGlass",
            url="https://shop.example/1",
            in_stock=True,
        )
        d = item.to_dict()
        assert d["name"] == "Windshield Lada Granta"
        assert d["price"] == "5000"
        assert d["currency"] == "RUB"
        assert d["in_stock"] is True

    def test_to_dict_defaults(self):
        item = ParsedItem(name="Glass")
        d = item.to_dict()
        assert d["name"] == "Glass"
        assert d["price"] is None
        assert d["currency"] is None
        assert d["shop"] is None
        assert d["url"] is None
        assert d["in_stock"] is None

    def test_from_dict_full(self):
        d = {
            "name": "Test",
            "price": "100",
            "currency": "USD",
            "shop": "Shop",
            "url": "https://x.com",
            "in_stock": False,
        }
        item = ParsedItem.from_dict(d)
        assert item.name == "Test"
        assert item.price == "100"
        assert item.in_stock is False

    def test_from_dict_missing_fields(self):
        item = ParsedItem.from_dict({"name": "X"})
        assert item.name == "X"
        assert item.price is None

    def test_from_dict_empty(self):
        item = ParsedItem.from_dict({})
        assert item.name == ""

    def test_roundtrip(self):
        item = ParsedItem(name="A", price="10", currency="EUR")
        d = item.to_dict()
        item2 = ParsedItem.from_dict(d)
        assert item2.name == item.name
        assert item2.price == item.price
        assert item2.currency == item.currency


class TestParseResult:
    def test_to_dict(self):
        r = ParseResult(
            source_url="https://example.com",
            items=[ParsedItem(name="A", price="1")],
            raw_text_excerpt="some text",
            errors=["warn"],
            fetched_at=1234567890.0,
        )
        d = r.to_dict()
        assert d["source_url"] == "https://example.com"
        assert len(d["items"]) == 1
        assert d["items"][0]["name"] == "A"
        assert d["raw_text_excerpt"] == "some text"
        assert d["errors"] == ["warn"]
        assert d["fetched_at"] == 1234567890.0

    def test_from_dict(self):
        d = {
            "source_url": "https://x.com",
            "items": [{"name": "B", "price": "2"}],
            "raw_text_excerpt": "txt",
            "errors": [],
            "fetched_at": 0.0,
        }
        r = ParseResult.from_dict(d)
        assert r.source_url == "https://x.com"
        assert len(r.items) == 1
        assert r.items[0].name == "B"

    def test_defaults(self):
        r = ParseResult(source_url="https://y.com")
        assert r.items == []
        assert r.errors == []
        assert r.raw_text_excerpt == ""
        assert r.fetched_at == 0.0

    def test_roundtrip(self):
        r = ParseResult(
            source_url="u",
            items=[ParsedItem(name="C")],
            errors=["e1"],
        )
        d = r.to_dict()
        r2 = ParseResult.from_dict(d)
        assert r2.source_url == r.source_url
        assert len(r2.items) == 1
        assert r2.items[0].name == "C"
        assert r2.errors == ["e1"]
