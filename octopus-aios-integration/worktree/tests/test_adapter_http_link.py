import httpx
import pytest

from swarm.memory.adapters.http_link import LinkAdapter
from swarm.memory.types import Artifact, MemoryAdapterError, RefNotFoundError


@pytest.mark.asyncio
async def test_link_get():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"OK"))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        art = await ad.get("ref:https:example.com%2F")
        assert art.content == b"OK"
        assert art.mime == "application/octet-stream"
        assert "trust:external" in art.tags
        assert art.provenance.get("url") == "https://example.com/"


@pytest.mark.asyncio
async def test_link_get_http_scheme():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"hey"))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client, scheme="http")
        art = await ad.get("ref:http:http%3A%2F%2Fexample.test%2Fp")
        assert art.content == b"hey"
        assert art.provenance["url"] == "http://example.test/p"


@pytest.mark.asyncio
async def test_link_get_content_type():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            content=b"{}",
            headers={"content-type": "application/json; charset=utf-8"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        art = await ad.get("ref:https:example.com%2F")
        assert art.mime == "application/json"


@pytest.mark.asyncio
async def test_link_get_wrong_scheme_raises():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x"))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client, scheme="https")
        with pytest.raises(RefNotFoundError):
            await ad.get("ref:http:http%3A%2F%2Fexample.com%2F")


@pytest.mark.asyncio
async def test_link_get_404_raises():
    transport = httpx.MockTransport(lambda r: httpx.Response(404, content=b""))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        with pytest.raises(RefNotFoundError):
            await ad.get("ref:https:example.com%2F")


@pytest.mark.asyncio
async def test_link_get_other_http_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(500, content=b"err"))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        with pytest.raises(MemoryAdapterError, match="HTTP 500"):
            await ad.get("ref:https:example.com%2F")


@pytest.mark.asyncio
async def test_link_put_raises():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        with pytest.raises(MemoryAdapterError, match="read-only"):
            await ad.put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_link_exists():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client, scheme="https")
        assert await ad.exists("ref:https:example.com%2F") is True
        assert await ad.exists("ref:http:example.com%2F") is False
        assert await ad.exists("not-a-ref") is False


@pytest.mark.asyncio
async def test_link_delete_returns_false():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        assert await ad.delete("ref:https:x") is False


@pytest.mark.asyncio
async def test_link_search_empty():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        assert await ad.search([], None) == []


@pytest.mark.asyncio
async def test_link_capabilities():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client, scheme="http")
        cap = ad.capabilities()
        assert cap.schemes == frozenset({"http"})
        assert cap.supports_search is False
        assert cap.supports_delete is False
        assert cap.supports_promote is False


@pytest.mark.asyncio
async def test_link_adapter_invalid_scheme():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            LinkAdapter(client, scheme="ftp")  # type: ignore[arg-type]
