"""Tests for swarm.parser.pipeline — the orchestrator."""

import json
from unittest.mock import AsyncMock

import pytest
from click import ClickException

from swarm.parser.extractor import Extractor
from swarm.parser.fetcher import Fetcher
from swarm.parser.models import ParseResult
from swarm.parser.pipeline import WebParserPipeline, _looks_like_url
from swarm.parser.resolver import Resolver


class TestLooksLikeUrl:
    def test_http(self):
        assert _looks_like_url("http://example.com") is True

    def test_https(self):
        assert _looks_like_url("https://shop.example.com/page") is True

    def test_with_spaces(self):
        assert _looks_like_url("  https://x.com  ") is True

    def test_not_url(self):
        assert _looks_like_url("autoglass granta price") is False

    def test_ftp(self):
        assert _looks_like_url("ftp://files.example.com") is False

    def test_empty(self):
        assert _looks_like_url("") is False

    def test_bare_domain(self):
        assert _looks_like_url("example.com") is False


class TestPipelineUrlMode:
    @pytest.mark.asyncio
    async def test_single_url_success(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=json.dumps({
            "items": [{"name": "Glass A", "price": "5000", "currency": "RUB"}]
        }))

        fetcher = AsyncMock(spec=Fetcher)
        fetcher.fetch_many = AsyncMock(return_value=[
            ParseResult(
                source_url="https://shop.com/parts",
                raw_text_excerpt="<html><body>Glass A 5000 RUB in stock</body></html>",
                fetched_at=100.0,
            )
        ])

        extractor = Extractor(llm)

        pipeline = WebParserPipeline(
            llm,
            fetcher=fetcher,
            extractor=extractor,
        )

        results = await pipeline.run("https://shop.com/parts", search=False)

        assert len(results) == 1
        assert results[0].source_url == "https://shop.com/parts"
        assert len(results[0].items) == 1
        assert results[0].items[0].name == "Glass A"

    @pytest.mark.asyncio
    async def test_non_url_without_search_raises(self):
        llm = AsyncMock()
        pipeline = WebParserPipeline(llm)

        with pytest.raises(ClickException, match="does not look like a URL"):
            await pipeline.run("autoglass price", search=False)

    @pytest.mark.asyncio
    async def test_url_with_fetch_error_degrades_gracefully(self):
        llm = AsyncMock()
        fetcher = AsyncMock(spec=Fetcher)
        fetcher.fetch_many = AsyncMock(return_value=[
            ParseResult(
                source_url="https://down.com",
                errors=["HTTP 500"],
                fetched_at=100.0,
            )
        ])

        extractor = Extractor(llm)
        pipeline = WebParserPipeline(llm, fetcher=fetcher, extractor=extractor)

        results = await pipeline.run("https://down.com", search=False)

        assert len(results) == 1
        assert "HTTP 500" in results[0].errors
        assert results[0].items == []
        # LLM should not have been called
        llm.complete.assert_not_called()


class TestPipelineSearchMode:
    @pytest.mark.asyncio
    async def test_search_resolves_and_parses(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=json.dumps({
            "items": [{"name": "Item", "price": "1000"}]
        }))

        resolver = AsyncMock(spec=Resolver)
        resolver.resolve = AsyncMock(return_value=[
            "https://result1.com",
            "https://result2.com",
        ])

        fetcher = AsyncMock(spec=Fetcher)
        fetcher.fetch_many = AsyncMock(return_value=[
            ParseResult(
                source_url="https://result1.com",
                raw_text_excerpt="<html><body>Item 1000 RUB</body></html>",
                fetched_at=100.0,
            ),
            ParseResult(
                source_url="https://result2.com",
                raw_text_excerpt="<html><body>Item 2000 RUB</body></html>",
                fetched_at=101.0,
            ),
        ])

        extractor = Extractor(llm)
        pipeline = WebParserPipeline(
            llm,
            resolver=resolver,
            fetcher=fetcher,
            extractor=extractor,
        )

        results = await pipeline.run("autoglass granta", search=True, limit=3)

        assert len(results) == 2
        resolver.resolve.assert_called_once_with("autoglass granta", limit=3)
        fetcher.fetch_many.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        llm = AsyncMock()
        resolver = AsyncMock(spec=Resolver)
        resolver.resolve = AsyncMock(return_value=[])

        pipeline = WebParserPipeline(llm, resolver=resolver)

        results = await pipeline.run("nothing", search=True, limit=3)

        assert len(results) == 1
        assert "resolver_returned_no_urls_for" in results[0].errors[0]

    @pytest.mark.asyncio
    async def test_limit_capped_at_10(self):
        llm = AsyncMock()
        resolver = AsyncMock(spec=Resolver)
        resolver.resolve = AsyncMock(return_value=["https://x.com"])

        fetcher = AsyncMock(spec=Fetcher)
        fetcher.fetch_many = AsyncMock(return_value=[
            ParseResult(source_url="https://x.com", raw_text_excerpt="<html><body>hi</body></html>")
        ])

        extractor = Extractor(llm)
        pipeline = WebParserPipeline(llm, resolver=resolver, fetcher=fetcher, extractor=extractor)

        await pipeline.run("query", search=True, limit=100)

        # limit should have been capped to 10
        resolver.resolve.assert_called_once_with("query", limit=10)

    @pytest.mark.asyncio
    async def test_limit_minimum_1(self):
        llm = AsyncMock()
        resolver = AsyncMock(spec=Resolver)
        resolver.resolve = AsyncMock(return_value=["https://x.com"])

        fetcher = AsyncMock(spec=Fetcher)
        fetcher.fetch_many = AsyncMock(return_value=[
            ParseResult(source_url="https://x.com", raw_text_excerpt="<html><body>x</body></html>")
        ])

        extractor = Extractor(llm)
        pipeline = WebParserPipeline(llm, resolver=resolver, fetcher=fetcher, extractor=extractor)

        await pipeline.run("q", search=True, limit=-5)

        resolver.resolve.assert_called_once_with("q", limit=1)


class TestPipelineEndToEnd:
    """Integration-style test with all components mocked at HTTP/LLM boundaries."""

    @pytest.mark.asyncio
    async def test_full_pipeline_url_mode(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=json.dumps({
            "items": [
                {"name": "Windshield", "price": "7500", "currency": "RUB", "shop": "GlassShop", "in_stock": True},
                {"name": "Side glass", "price": "2000", "currency": "RUB", "in_stock": False},
            ]
        }))

        fetcher = AsyncMock(spec=Fetcher)
        fetcher.fetch_many = AsyncMock(return_value=[
            ParseResult(
                source_url="https://glass-shop.ru/catalog",
                raw_text_excerpt=(
                    "<html><body>"
                    "<div>Windshield Lada Granta - 7500 RUB, in stock</div>"
                    "<div>Side glass - 2000 RUB, out of stock</div>"
                    "</body></html>"
                ),
                fetched_at=1700000000.0,
            )
        ])

        extractor = Extractor(llm)
        pipeline = WebParserPipeline(llm, fetcher=fetcher, extractor=extractor)

        results = await pipeline.run("https://glass-shop.ru/catalog", search=False)

        assert len(results) == 1
        assert len(results[0].items) == 2
        assert results[0].items[0].name == "Windshield"
        assert results[0].items[0].price == "7500"
        assert results[0].items[0].in_stock is True
        assert results[0].items[1].in_stock is False
        assert results[0].errors == []

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self):
        """One URL succeeds, another fails — pipeline doesn't crash."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=json.dumps({
            "items": [{"name": "OK Item", "price": "100"}]
        }))

        resolver = AsyncMock(spec=Resolver)
        resolver.resolve = AsyncMock(return_value=[
            "https://good.com",
            "https://bad.com",
        ])

        fetcher = AsyncMock(spec=Fetcher)
        fetcher.fetch_many = AsyncMock(return_value=[
            ParseResult(
                source_url="https://good.com",
                raw_text_excerpt="<html><body>OK Item 100</body></html>",
                fetched_at=100.0,
            ),
            ParseResult(
                source_url="https://bad.com",
                errors=["timeout"],
                fetched_at=101.0,
            ),
        ])

        extractor = Extractor(llm)
        pipeline = WebParserPipeline(
            llm,
            resolver=resolver,
            fetcher=fetcher,
            extractor=extractor,
        )

        results = await pipeline.run("query", search=True, limit=5)

        assert len(results) == 2
        # First succeeded
        assert len(results[0].items) == 1
        assert results[0].items[0].name == "OK Item"
        # Second failed gracefully
        assert results[1].items == []
        assert "timeout" in results[1].errors
