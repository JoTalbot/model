"""Tests for swarm.parser.fetcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm.parser.fetcher import Fetcher


def _mock_response(status_code=200, text="<html><body>OK</body></html>"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    return resp


class TestFetcher:
    @pytest.mark.asyncio
    async def test_fetch_success(self):
        fetcher = Fetcher(timeout=5, polite_delay=0)
        resp = _mock_response(200, "<html><body>Hello</body></html>")

        with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
            mock_inst = AsyncMock()
            mock_inst.get = AsyncMock(return_value=resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await fetcher.fetch_many(["https://example.com"])

        assert len(results) == 1
        assert results[0].source_url == "https://example.com"
        assert results[0].raw_text_excerpt == "<html><body>Hello</body></html>"
        assert results[0].errors == []

    @pytest.mark.asyncio
    async def test_fetch_http_error(self):
        fetcher = Fetcher(timeout=5, polite_delay=0)
        resp = _mock_response(403)

        with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
            mock_inst = AsyncMock()
            mock_inst.get = AsyncMock(return_value=resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await fetcher.fetch_many(["https://blocked.com"])

        assert len(results) == 1
        assert "HTTP 403" in results[0].errors[0]
        assert results[0].raw_text_excerpt == ""

    @pytest.mark.asyncio
    async def test_fetch_timeout(self):
        fetcher = Fetcher(timeout=1, polite_delay=0)

        with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
            mock_inst = AsyncMock()
            mock_inst.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await fetcher.fetch_many(["https://slow.com"])

        assert len(results) == 1
        assert "timeout" in results[0].errors[0]

    @pytest.mark.asyncio
    async def test_fetch_network_error(self):
        fetcher = Fetcher(timeout=1, polite_delay=0)

        with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
            mock_inst = AsyncMock()
            mock_inst.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await fetcher.fetch_many(["https://down.com"])

        assert len(results) == 1
        assert "fetch_error" in results[0].errors[0]

    @pytest.mark.asyncio
    async def test_fetch_truncates_large_body(self):
        fetcher = Fetcher(timeout=5, max_bytes=100, polite_delay=0)
        large_body = "X" * 500
        resp = _mock_response(200, large_body)

        with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
            mock_inst = AsyncMock()
            mock_inst.get = AsyncMock(return_value=resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await fetcher.fetch_many(["https://big.com"])

        assert len(results[0].raw_text_excerpt) == 100

    @pytest.mark.asyncio
    async def test_fetch_many_sequential(self):
        """Multiple URLs are fetched and each gets a result."""
        fetcher = Fetcher(timeout=5, polite_delay=0)
        resp = _mock_response(200, "<html>ok</html>")

        with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
            mock_inst = AsyncMock()
            mock_inst.get = AsyncMock(return_value=resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await fetcher.fetch_many([
                "https://a.com",
                "https://b.com",
                "https://c.com",
            ])

        assert len(results) == 3
        assert all(r.errors == [] for r in results)

    @pytest.mark.asyncio
    async def test_fetched_at_populated(self):
        fetcher = Fetcher(timeout=5, polite_delay=0)
        resp = _mock_response(200, "<html>ok</html>")

        with patch("swarm.parser.fetcher.httpx.AsyncClient") as MockClient:
            mock_inst = AsyncMock()
            mock_inst.get = AsyncMock(return_value=resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_inst)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await fetcher.fetch_many(["https://ts.com"])

        assert results[0].fetched_at > 0
