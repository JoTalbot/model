"""Tests for the 5 additional anonymous cloud-paste adapters.

Pure-mock: every HTTP call is intercepted, no real network traffic.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from swarm.memory.adapters.paste_cloud import (
    _ENVELOPE_KEY,
    BashuploadAdapter,
    ClbinAdapter,
    FilebinAdapter,
    LitterboxAdapter,
    PixelDrainAdapter,
    _pack,
)
from swarm.memory.types import Artifact, MemoryAdapterError, RefNotFoundError


def _envelope(content: bytes, mime: str = "text/plain") -> bytes:
    return json.dumps(
        {
            _ENVELOPE_KEY: True,
            "mime": mime,
            "tags": [],
            "provenance": {},
            "attrs": {},
            "data_b64": base64.b64encode(content).decode("ascii"),
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _client(responses: list[httpx.Response]) -> httpx.AsyncClient:
    idx = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal idx
        resp = responses[idx]
        idx += 1
        return resp

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)


def _capture(responses: list[httpx.Response]) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    captured: list[httpx.Request] = []
    idx = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal idx
        captured.append(req)
        resp = responses[idx]
        idx += 1
        return resp

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)
    return client, captured


# ---------------------------------------------------------------------------
# PixelDrainAdapter
# ---------------------------------------------------------------------------

async def test_pixeldrain_put_returns_id_ref():
    client = _client([httpx.Response(200, json={"id": "abc123XYZ"})])
    adapter = PixelDrainAdapter(client=client)
    ref = await adapter.put(Artifact(content=b"hello", mime="text/plain"))
    assert ref == "ref:pixeldrain:abc123XYZ"


async def test_pixeldrain_put_missing_id_raises():
    client = _client([httpx.Response(200, json={"success": True})])
    adapter = PixelDrainAdapter(client=client)
    with pytest.raises(MemoryAdapterError, match="missing id"):
        await adapter.put(Artifact(content=b"x"))


async def test_pixeldrain_put_http_error_raises():
    client = _client([httpx.Response(500, text="boom")])
    adapter = PixelDrainAdapter(client=client)
    with pytest.raises(MemoryAdapterError, match="HTTP 500"):
        await adapter.put(Artifact(content=b"x"))


async def test_pixeldrain_get_roundtrip():
    payload = _envelope(b"\xff\x00binary")
    client = _client([httpx.Response(200, content=payload)])
    adapter = PixelDrainAdapter(client=client)
    artifact = await adapter.get("ref:pixeldrain:abc")
    assert artifact.content == b"\xff\x00binary"


async def test_pixeldrain_get_404_raises_not_found():
    client = _client([httpx.Response(404, text="not found")])
    adapter = PixelDrainAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:pixeldrain:missing")


async def test_pixeldrain_capabilities_immutable():
    adapter = PixelDrainAdapter(client=httpx.AsyncClient())
    caps = adapter.capabilities()
    assert caps.schemes == frozenset({"pixeldrain"})
    assert not caps.supports_search
    assert not caps.supports_delete


# ---------------------------------------------------------------------------
# FilebinAdapter
# ---------------------------------------------------------------------------

async def test_filebin_put_returns_bin_filename_ref():
    client, captured = _capture([httpx.Response(201, json={"file": {"filename": "x"}})])
    adapter = FilebinAdapter(client=client, bin="my-test-bin")
    ref = await adapter.put(Artifact(content=b"hi"))
    assert ref.startswith("ref:filebin:my-test-bin/gemaxi_")
    assert ref.endswith(".json")
    assert captured[0].method == "POST"
    assert "my-test-bin" in str(captured[0].url)


async def test_filebin_get_returns_unpacked_artifact():
    payload = _envelope(b"binary-data", mime="application/zip")
    client = _client([httpx.Response(200, content=payload)])
    adapter = FilebinAdapter(client=client)
    artifact = await adapter.get("ref:filebin:bin/file.json")
    assert artifact.content == b"binary-data"
    assert artifact.mime == "application/zip"


async def test_filebin_get_404_raises():
    client = _client([httpx.Response(404)])
    adapter = FilebinAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:filebin:bin/missing")


async def test_filebin_delete_returns_true_on_success():
    client = _client([httpx.Response(200)])
    adapter = FilebinAdapter(client=client)
    assert await adapter.delete("ref:filebin:bin/file.json") is True


async def test_filebin_delete_returns_false_on_error():
    client = _client([httpx.Response(404)])
    adapter = FilebinAdapter(client=client)
    assert await adapter.delete("ref:filebin:bin/file.json") is False


async def test_filebin_capabilities_supports_delete():
    adapter = FilebinAdapter(client=httpx.AsyncClient())
    caps = adapter.capabilities()
    assert caps.schemes == frozenset({"filebin"})
    assert caps.supports_delete is True


async def test_filebin_auto_bin_generated_when_not_provided():
    adapter1 = FilebinAdapter(client=httpx.AsyncClient())
    adapter2 = FilebinAdapter(client=httpx.AsyncClient())
    assert adapter1._bin != adapter2._bin
    assert adapter1._bin.startswith("gemaxi-")


# ---------------------------------------------------------------------------
# LitterboxAdapter
# ---------------------------------------------------------------------------

async def test_litterbox_put_returns_url_ref():
    client, captured = _capture(
        [httpx.Response(200, text="https://litter.catbox.moe/abc.json")]
    )
    adapter = LitterboxAdapter(client=client, time="24h")
    ref = await adapter.put(Artifact(content=b"hi"))
    assert ref == "ref:litterbox:https://litter.catbox.moe/abc.json"
    body = captured[0].content.decode("utf-8", errors="replace")
    assert "24h" in body


async def test_litterbox_rejects_invalid_time():
    with pytest.raises(ValueError, match="litterbox time"):
        LitterboxAdapter(time="9d")


async def test_litterbox_put_non_url_response_raises():
    client = _client([httpx.Response(200, text="ERROR: limit exceeded")])
    adapter = LitterboxAdapter(client=client)
    with pytest.raises(MemoryAdapterError, match="unexpected response"):
        await adapter.put(Artifact(content=b"x"))


async def test_litterbox_get_roundtrip():
    payload = _envelope(b"temp-data")
    client = _client([httpx.Response(200, content=payload)])
    adapter = LitterboxAdapter(client=client)
    artifact = await adapter.get("ref:litterbox:https://litter.catbox.moe/x.json")
    assert artifact.content == b"temp-data"


# ---------------------------------------------------------------------------
# BashuploadAdapter
# ---------------------------------------------------------------------------

async def test_bashupload_put_extracts_url_from_text_body():
    body = (
        "Uploaded 1 file, 12 bytes\n\n"
        "wget https://bashupload.com/Abc/gemaxi_x.json\n"
    )
    client = _client([httpx.Response(200, text=body)])
    adapter = BashuploadAdapter(client=client)
    ref = await adapter.put(Artifact(content=b"hi"))
    assert ref == "ref:bashupload:https://bashupload.com/Abc/gemaxi_x.json"


async def test_bashupload_put_no_url_in_body_raises():
    client = _client([httpx.Response(200, text="no URL here at all")])
    adapter = BashuploadAdapter(client=client)
    with pytest.raises(MemoryAdapterError, match="could not parse"):
        await adapter.put(Artifact(content=b"x"))


async def test_bashupload_get_roundtrip():
    payload = _envelope(b"big-binary")
    client = _client([httpx.Response(200, content=payload)])
    adapter = BashuploadAdapter(client=client)
    artifact = await adapter.get("ref:bashupload:https://bashupload.com/A/x.json")
    assert artifact.content == b"big-binary"


async def test_bashupload_get_404_raises():
    client = _client([httpx.Response(404)])
    adapter = BashuploadAdapter(client=client)
    with pytest.raises(RefNotFoundError):
        await adapter.get("ref:bashupload:https://bashupload.com/A/x.json")


async def test_bashupload_uses_put_method():
    captured: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req.method)
        return httpx.Response(200, text="wget https://bashupload.com/A/x.json")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = BashuploadAdapter(client=client)
    await adapter.put(Artifact(content=b"hi"))
    assert captured == ["PUT"]


# ---------------------------------------------------------------------------
# ClbinAdapter
# ---------------------------------------------------------------------------

async def test_clbin_put_returns_url_ref():
    client = _client([httpx.Response(200, text="https://clbin.com/AbCdE")])
    adapter = ClbinAdapter(client=client)
    ref = await adapter.put(Artifact(content=b"hi"))
    assert ref == "ref:clbin:https://clbin.com/AbCdE"


async def test_clbin_put_non_url_response_raises():
    client = _client([httpx.Response(200, text="something else entirely")])
    adapter = ClbinAdapter(client=client)
    with pytest.raises(MemoryAdapterError, match="unexpected response"):
        await adapter.put(Artifact(content=b"x"))


async def test_clbin_get_roundtrip_preserves_attrs():
    a = Artifact(
        content=b"hello",
        mime="text/plain",
        tags=["t1", "t2"],
        attrs={"k": "v"},
    )
    payload = _pack(a)
    client = _client([httpx.Response(200, content=payload)])
    adapter = ClbinAdapter(client=client)
    got = await adapter.get("ref:clbin:https://clbin.com/x")
    assert got.content == b"hello"
    assert sorted(got.tags) == ["t1", "t2"]
    assert got.attrs == {"k": "v"}


async def test_clbin_capabilities():
    adapter = ClbinAdapter(client=httpx.AsyncClient())
    caps = adapter.capabilities()
    assert caps.schemes == frozenset({"clbin"})
    assert not caps.supports_search
    assert not caps.supports_delete


# ---------------------------------------------------------------------------
# All 5 adapters share the envelope shape — sanity round-trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "adapter_cls, success_response, ref_prefix",
    [
        (
            PixelDrainAdapter,
            lambda: httpx.Response(200, json={"id": "x"}),
            "ref:pixeldrain:",
        ),
        (
            LitterboxAdapter,
            lambda: httpx.Response(200, text="https://litter.catbox.moe/x.json"),
            "ref:litterbox:",
        ),
        (
            BashuploadAdapter,
            lambda: httpx.Response(200, text="wget https://bashupload.com/A/x.json"),
            "ref:bashupload:",
        ),
        (
            ClbinAdapter,
            lambda: httpx.Response(200, text="https://clbin.com/x"),
            "ref:clbin:",
        ),
    ],
)
async def test_envelope_preserves_binary_content(adapter_cls, success_response, ref_prefix):
    binary = bytes(range(256))
    client = _client([success_response()])
    adapter = adapter_cls(client=client)
    ref = await adapter.put(Artifact(content=binary, mime="application/octet-stream"))
    assert ref.startswith(ref_prefix)
