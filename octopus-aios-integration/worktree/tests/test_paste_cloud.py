"""Tests for free anonymous cloud-paste memory adapters.

All HTTP calls are intercepted with ``httpx.MockTransport`` — no real network
traffic is made during the test suite.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from swarm.memory.adapters.paste_cloud import (
    _ENVELOPE_KEY,
    CatboxAdapter,
    DpasteAdapter,
    FileIoAdapter,
    IxioAdapter,
    NullpointerAdapter,
    _pack,
    _unpack,
)
from swarm.memory.types import (
    Artifact,
    MemoryAdapterError,
    RefNotFoundError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _envelope(content: bytes, mime: str = "text/plain") -> bytes:
    return json.dumps(
        {
            _ENVELOPE_KEY: True,
            "mime": mime,
            "tags": ["hello"],
            "provenance": {},
            "attrs": {},
            "data_b64": base64.b64encode(content).decode("ascii"),
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _make_client(responses: list[httpx.Response]) -> httpx.AsyncClient:
    """Return an AsyncClient backed by a sequence of canned responses."""
    idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal idx
        resp = responses[idx]
        idx += 1
        return resp

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=10.0)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def test_pack_unpack_roundtrip_bytes():
    art = Artifact(
        content=b"\x00\x01\x02\xff",
        mime="application/octet-stream",
        tags=["bin"],
        provenance={"src": "test"},
        attrs={"store": "nullpointer"},
    )
    packed = _pack(art)
    recovered = _unpack(packed)
    assert recovered.content == b"\x00\x01\x02\xff"
    assert recovered.mime == "application/octet-stream"
    assert recovered.tags == ["bin"]
    assert recovered.provenance == {"src": "test"}
    assert recovered.attrs == {"store": "nullpointer"}


def test_pack_unpack_roundtrip_str():
    art = Artifact(content="привет мир", mime="text/plain")
    packed = _pack(art)
    recovered = _unpack(packed)
    assert recovered.content == "привет мир".encode()


def test_unpack_raw_bytes_fallback():
    raw = b"just plain bytes, no envelope"
    art = _unpack(raw)
    assert art.content == raw
    assert art.mime == "application/octet-stream"


# ---------------------------------------------------------------------------
# NullpointerAdapter (0x0.st)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nullpointer_put_get_roundtrip():
    content = b"autoglass data"
    artifact = Artifact(content=content, mime="text/plain", tags=["price"])

    upload_resp = httpx.Response(200, text="https://0x0.st/AbCd")
    download_resp = httpx.Response(200, content=_envelope(content, "text/plain"))

    client = _make_client([upload_resp, download_resp])
    adapter = NullpointerAdapter(client=client)

    ref = await adapter.put(artifact)
    assert ref == "ref:nullpointer:https://0x0.st/AbCd"

    recovered = await adapter.get(ref)
    assert recovered.content == content
    assert recovered.mime == "text/plain"


@pytest.mark.asyncio
async def test_nullpointer_get_404_raises():
    client = _make_client([httpx.Response(404)])
    adapter = NullpointerAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:nullpointer:https://0x0.st/gone")


@pytest.mark.asyncio
async def test_nullpointer_put_bad_response_raises():
    client = _make_client([httpx.Response(500, text="internal error")])
    adapter = NullpointerAdapter(client=client)
    with pytest.raises(MemoryAdapterError):
        await adapter.put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_nullpointer_503_suggests_alternatives():
    client = _make_client(
        [httpx.Response(503, text="uploads disabled because spam")]
    )
    adapter = NullpointerAdapter(client=client)
    with pytest.raises(MemoryAdapterError, match="pasters"):
        await adapter.put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_nullpointer_delete_returns_false():
    adapter = NullpointerAdapter(client=httpx.AsyncClient())
    assert await adapter.delete("ref:nullpointer:https://0x0.st/x") is False


@pytest.mark.asyncio
async def test_nullpointer_search_returns_empty():
    adapter = NullpointerAdapter(client=httpx.AsyncClient())
    assert await adapter.search(["t"], None) == []


def test_nullpointer_capabilities():
    caps = NullpointerAdapter(client=httpx.AsyncClient()).capabilities()
    assert "nullpointer" in caps.schemes
    assert caps.supports_delete is False
    assert caps.supports_search is False
    assert caps.supports_promote is False


# ---------------------------------------------------------------------------
# CatboxAdapter (catbox.moe)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_catbox_put_get_roundtrip():
    content = b"windshield price 4200"
    artifact = Artifact(content=content, mime="text/plain", tags=["catbox"])

    upload_resp = httpx.Response(200, text="https://files.catbox.moe/abc123.json")
    download_resp = httpx.Response(200, content=_envelope(content, "text/plain"))

    client = _make_client([upload_resp, download_resp])
    adapter = CatboxAdapter(client=client)

    ref = await adapter.put(artifact)
    assert ref == "ref:catbox:https://files.catbox.moe/abc123.json"

    recovered = await adapter.get(ref)
    assert recovered.content == content


@pytest.mark.asyncio
async def test_catbox_get_404_raises():
    client = _make_client([httpx.Response(404)])
    adapter = CatboxAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:catbox:https://files.catbox.moe/gone.json")


@pytest.mark.asyncio
async def test_catbox_put_server_error_raises():
    client = _make_client([httpx.Response(503, text="unavailable")])
    adapter = CatboxAdapter(client=client)
    with pytest.raises(MemoryAdapterError):
        await adapter.put(Artifact(content=b"data"))


@pytest.mark.asyncio
async def test_catbox_delete_returns_false():
    adapter = CatboxAdapter(client=httpx.AsyncClient())
    assert await adapter.delete("ref:catbox:https://files.catbox.moe/x.json") is False


def test_catbox_capabilities():
    caps = CatboxAdapter(client=httpx.AsyncClient()).capabilities()
    assert "catbox" in caps.schemes
    assert caps.supports_delete is False


# ---------------------------------------------------------------------------
# FileIoAdapter (file.io)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fileio_put_get_roundtrip():
    content = b"temp data"
    artifact = Artifact(content=content, mime="application/octet-stream")

    upload_body = json.dumps(
        {"success": True, "key": "tEsTkEy99", "link": "https://file.io/tEsTkEy99"}
    )
    upload_resp = httpx.Response(200, text=upload_body)
    download_resp = httpx.Response(200, content=_envelope(content))

    client = _make_client([upload_resp, download_resp])
    adapter = FileIoAdapter(client=client)

    ref = await adapter.put(artifact)
    assert ref == "ref:fileio:tEsTkEy99"

    recovered = await adapter.get(ref)
    assert recovered.content == content


@pytest.mark.asyncio
async def test_fileio_put_non_success_raises():
    upload_body = json.dumps({"success": False, "message": "limit exceeded"})
    client = _make_client([httpx.Response(200, text=upload_body)])
    adapter = FileIoAdapter(client=client)
    with pytest.raises(MemoryAdapterError):
        await adapter.put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_fileio_get_404_raises():
    client = _make_client([httpx.Response(404)])
    adapter = FileIoAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:fileio:gone123")


@pytest.mark.asyncio
async def test_fileio_delete_returns_false():
    adapter = FileIoAdapter(client=httpx.AsyncClient())
    assert await adapter.delete("ref:fileio:somekey") is False


def test_fileio_capabilities():
    caps = FileIoAdapter(client=httpx.AsyncClient()).capabilities()
    assert "fileio" in caps.schemes
    assert caps.supports_delete is False


# ---------------------------------------------------------------------------
# DpasteAdapter (dpaste.org)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dpaste_put_get_roundtrip():
    content = b"car parts list"
    artifact = Artifact(content=content, mime="text/plain", tags=["parts"])

    upload_resp = httpx.Response(200, text="https://dpaste.org/XYZAB/")
    download_resp = httpx.Response(200, content=_envelope(content, "text/plain"))

    client = _make_client([upload_resp, download_resp])
    adapter = DpasteAdapter(client=client)

    ref = await adapter.put(artifact)
    assert ref == "ref:dpaste:XYZAB"

    recovered = await adapter.get(ref)
    assert recovered.content == content


@pytest.mark.asyncio
async def test_dpaste_put_error_raises():
    client = _make_client([httpx.Response(400, text="bad request")])
    adapter = DpasteAdapter(client=client)
    with pytest.raises(MemoryAdapterError):
        await adapter.put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_dpaste_405_suggests_alternatives():
    client = _make_client([httpx.Response(405, text="halted")])
    adapter = DpasteAdapter(client=client)
    with pytest.raises(MemoryAdapterError, match="pasters"):
        await adapter.put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_dpaste_get_404_raises():
    client = _make_client([httpx.Response(404)])
    adapter = DpasteAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:dpaste:NOSUCHSLUG")


@pytest.mark.asyncio
async def test_dpaste_delete_returns_false():
    adapter = DpasteAdapter(client=httpx.AsyncClient())
    assert await adapter.delete("ref:dpaste:ANYSLUG") is False


def test_dpaste_capabilities():
    caps = DpasteAdapter(client=httpx.AsyncClient()).capabilities()
    assert "dpaste" in caps.schemes
    assert caps.supports_delete is False
    assert caps.supports_search is False


# ---------------------------------------------------------------------------
# IxioAdapter (ix.io)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ixio_put_get_roundtrip():
    content = "разбор авто".encode()
    artifact = Artifact(content=content, mime="text/plain", tags=["ixio"])

    upload_resp = httpx.Response(200, text="http://ix.io/4AbC\n")
    download_resp = httpx.Response(200, content=_envelope(content, "text/plain"))

    client = _make_client([upload_resp, download_resp])
    adapter = IxioAdapter(client=client)

    ref = await adapter.put(artifact)
    assert ref == "ref:ixio:4AbC"

    recovered = await adapter.get(ref)
    assert recovered.content == content


@pytest.mark.asyncio
async def test_ixio_put_error_raises():
    client = _make_client([httpx.Response(500, text="server error")])
    adapter = IxioAdapter(client=client)
    with pytest.raises(MemoryAdapterError):
        await adapter.put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_ixio_get_404_raises():
    client = _make_client([httpx.Response(404)])
    adapter = IxioAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:ixio:NOPE")


@pytest.mark.asyncio
async def test_ixio_delete_returns_false():
    adapter = IxioAdapter(client=httpx.AsyncClient())
    assert await adapter.delete("ref:ixio:path") is False


def test_ixio_capabilities():
    caps = IxioAdapter(client=httpx.AsyncClient()).capabilities()
    assert "ixio" in caps.schemes
    assert caps.supports_delete is False


# ---------------------------------------------------------------------------
# CompositeMemoryPort routing to cloud adapters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_composite_routes_to_nullpointer(tmp_path):
    """CompositeMemoryPort sends put to nullpointer when attrs["store"]="nullpointer"."""
    from unittest.mock import AsyncMock, MagicMock

    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.types import Capabilities

    null_mock = MagicMock()
    null_mock.capabilities = MagicMock(
        return_value=Capabilities(
            schemes=frozenset({"nullpointer"}),
            supports_search=False,
            supports_delete=False,
            supports_promote=False,
        )
    )
    null_mock.put = AsyncMock(return_value="ref:nullpointer:https://0x0.st/ZZ")

    comp = CompositeMemoryPort(
        {"file": LocalScratchAdapter(tmp_path), "nullpointer": null_mock}
    )

    ref = await comp.put(Artifact(content=b"data", attrs={"store": "nullpointer"}))
    assert ref == "ref:nullpointer:https://0x0.st/ZZ"
    null_mock.put.assert_awaited_once()
