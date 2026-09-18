"""Tests for swarm.parser.resolver."""

from unittest.mock import AsyncMock, patch

import pytest

from swarm.parser.resolver import (
    Resolver,
    _extract_links_from_html,
    _is_organic_url,
    _random_ua,
)


class TestIsOrganicUrl:
    def test_valid_http(self):
        assert _is_organic_url("https://shop.example.com/parts") is True

    def test_valid_http_no_www(self):
        assert _is_organic_url("http://example.org/page") is True

    def test_rejects_empty(self):
        assert _is_organic_url("") is False

    def test_rejects_none_like(self):
        assert _is_organic_url("#") is False
        assert _is_organic_url("javascript:void(0)") is False

    def test_rejects_yandex(self):
        assert _is_organic_url("https://yandex.ru/search?text=foo") is False

    def test_rejects_google(self):
        assert _is_organic_url("https://www.google.com/search?q=x") is False

    def test_rejects_duckduckgo(self):
        assert _is_organic_url("https://duckduckgo.com/?q=test") is False

    def test_rejects_bing(self):
        assert _is_organic_url("https://www.bing.com/search?q=x") is False

    def test_rejects_non_http(self):
        assert _is_organic_url("ftp://files.example.com/a") is False


class TestExtractLinks:
    FIXTURE_HTML = """
    <html><body>
    <a href="https://yandex.ru/search">yandex</a>
    <a href="https://shop1.com/product">Shop 1</a>
    <a href="https://shop2.com/catalog">Shop 2</a>
    <a href="https://shop1.com/product">Shop 1 dup</a>
    <a href="https://shop3.com/item">Shop 3</a>
    <a href="javascript:void(0)">js link</a>
    <a href="#">anchor</a>
    </body></html>
    """

    def test_extracts_organic_links(self):
        urls = _extract_links_from_html(self.FIXTURE_HTML, limit=10)
        assert "https://shop1.com/product" in urls
        assert "https://shop2.com/catalog" in urls
        assert "https://shop3.com/item" in urls
        # yandex, js, #  should be excluded
        assert all("yandex" not in u for u in urls)

    def test_deduplicates(self):
        urls = _extract_links_from_html(self.FIXTURE_HTML, limit=10)
        assert urls.count("https://shop1.com/product") == 1

    def test_respects_limit(self):
        urls = _extract_links_from_html(self.FIXTURE_HTML, limit=2)
        assert len(urls) == 2

    def test_empty_html(self):
        assert _extract_links_from_html("<html></html>", limit=5) == []

    def test_no_anchor_tags(self):
        assert _extract_links_from_html("<html><body><p>text</p></body></html>", limit=5) == []


class TestRandomUA:
    def test_returns_string(self):
        ua = _random_ua()
        assert isinstance(ua, str)
        assert len(ua) > 20


class TestResolver:
    @pytest.mark.asyncio
    async def test_resolve_yandex_success(self):
        html = '<html><body><a href="https://result.com/1">R1</a></body></html>'
        resolver = Resolver()

        with patch.object(resolver, "_fetch", new_callable=AsyncMock, return_value=html):
            urls = await resolver.resolve("test query", limit=3)

        assert urls == ["https://result.com/1"]

    @pytest.mark.asyncio
    async def test_resolve_yandex_fails_ddg_fallback(self):
        ddg_html = '<html><body><a href="https://ddg-result.com/page">DDG</a></body></html>'
        resolver = Resolver()

        call_count = 0

        async def mock_fetch(url):
            nonlocal call_count
            call_count += 1
            if "yandex" in url:
                return None  # yandex failed
            return ddg_html

        with patch.object(resolver, "_fetch", side_effect=mock_fetch):
            urls = await resolver.resolve("test", limit=3)

        assert call_count == 2
        assert urls == ["https://ddg-result.com/page"]

    @pytest.mark.asyncio
    async def test_resolve_yandex_empty_results_ddg_fallback(self):
        yandex_html = '<html><body><p>no links here</p></body></html>'
        ddg_html = '<html><body><a href="https://fallback.com/x">F</a></body></html>'
        resolver = Resolver()

        async def mock_fetch(url):
            if "yandex" in url:
                return yandex_html
            return ddg_html

        with patch.object(resolver, "_fetch", side_effect=mock_fetch):
            urls = await resolver.resolve("test", limit=3)

        assert urls == ["https://fallback.com/x"]

    @pytest.mark.asyncio
    async def test_resolve_both_fail(self):
        resolver = Resolver()
        with patch.object(resolver, "_fetch", new_callable=AsyncMock, return_value=None):
            urls = await resolver.resolve("nothing", limit=3)
        assert urls == []
