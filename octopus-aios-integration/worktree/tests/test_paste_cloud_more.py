"""Tests for the 8 new anonymous cloud-paste adapters.

All HTTP and TCP calls are intercepted: no real network traffic occurs.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from swarm.memory.adapters.paste_cloud import (
    _ENVELOPE_KEY,
    HastebinAdapter,
    PasteEEAdapter,
    PasteRsAdapter,
    RentryAdapter,
    SprungeAdapter,
    TelegraphAdapter,
    TermbinAdapter,
    TmpFilesAdapter,
    TransferShAdapter,
    _pack,
    _telegraph_extract_text,
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


# ---------------------------------------------------------------------------
# TelegraphAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telegraph_put_get_roundtrip():
    content = b"wiki block"
    envelope_text = _pack(Artifact(content=content, mime="text/plain")).decode("utf-8")

    upload_resp = httpx.Response(
        200,
        json={"ok": True, "result": {"access_token": "tok"}},
    )
    page_resp = httpx.Response(
        200,
        json={"ok": True, "result": {"path": "Gemaxi-12-31"}},
    )
    get_resp = httpx.Response(
        200,
        json={
            "ok": True,
            "result": {"content": [{"tag": "pre", "children": [envelope_text]}]},
        },
    )

    client = _client([upload_resp, page_resp, get_resp])
    a = TelegraphAdapter(client=client)
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:telegraph:Gemaxi-12-31"
    recovered = await a.get(ref)
    assert recovered.content == content


@pytest.mark.asyncio
async def test_telegraph_get_404_raises():
    a = TelegraphAdapter(client=_client([httpx.Response(404)]))
    with pytest.raises(RefNotFoundError):
        await a.get("ref:telegraph:nope")


def test_telegraph_extract_text_nested():
    nodes = [
        {"tag": "pre", "children": ["abc", {"tag": "code", "children": ["def"]}]},
    ]
    assert _telegraph_extract_text(nodes) == "abcdef"


def test_telegraph_capabilities():
    caps = TelegraphAdapter(client=httpx.AsyncClient()).capabilities()
    assert "telegraph" in caps.schemes
    assert caps.supports_delete is False


# ---------------------------------------------------------------------------
# RentryAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rentry_put_get_roundtrip():
    content = b"rentry data"
    envelope = _pack(Artifact(content=content, mime="text/plain")).decode("utf-8")
    raw_resp_text = "```json\n" + envelope + "\n```"

    csrf_page = httpx.Response(
        200,
        text='<input name="csrfmiddlewaretoken" value="CSRF123">',
        headers={"set-cookie": "csrftoken=cookieabc; Path=/"},
    )
    upload_resp = httpx.Response(
        200, json={"status": "200", "url": "abc123", "edit_code": "ed1"}
    )
    raw_resp = httpx.Response(200, text=raw_resp_text)

    client = _client([csrf_page, upload_resp, raw_resp])
    a = RentryAdapter(client=client)
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:rentry:abc123"
    art = await a.get(ref)
    assert art.content == content


@pytest.mark.asyncio
async def test_rentry_put_error_raises():
    csrf_page = httpx.Response(200, text='value="CSRF"')
    client = _client([csrf_page, httpx.Response(500, text="boom")])
    with pytest.raises(MemoryAdapterError):
        await RentryAdapter(client=client).put(Artifact(content=b"x"))


@pytest.mark.asyncio
async def test_rentry_get_404_raises():
    a = RentryAdapter(client=_client([httpx.Response(404)]))
    with pytest.raises(RefNotFoundError):
        await a.get("ref:rentry:gone")


# ---------------------------------------------------------------------------
# PasteEEAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pasteee_put_get_roundtrip():
    content = b"pasteee data"
    envelope = _pack(Artifact(content=content, mime="text/plain")).decode("utf-8")
    up = httpx.Response(200, json={"success": True, "id": "PID9", "link": "x"})
    dl = httpx.Response(
        200,
        json={
            "success": True,
            "paste": {"sections": [{"contents": envelope}]},
        },
    )
    a = PasteEEAdapter(client=_client([up, dl]), api_key="test-key-9")
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:pasteee:PID9"
    art = await a.get(ref)
    assert art.content == content


@pytest.mark.asyncio
async def test_pasteee_put_accepts_id_only_response():
    """API may return ``{"id","link"}`` without ``success`` on create."""
    up = httpx.Response(200, json={"id": "abc12", "link": "https://paste.ee/p/abc12"})
    a = PasteEEAdapter(client=_client([up]), api_key="k")
    ref = await a.put(Artifact(content=b"x", mime="text/plain"))
    assert ref == "ref:pasteee:abc12"


@pytest.mark.asyncio
async def test_pasteee_put_sends_x_auth_token():
    last: dict[str, str | None] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        last["token"] = req.headers.get("x-auth-token")
        return httpx.Response(200, json={"id": "z1", "link": "https://paste.ee/p/z1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)
    a = PasteEEAdapter(client=client, api_key="secret-token")
    await a.put(Artifact(content=b"x", mime="text/plain"))
    assert last["token"] == "secret-token"


@pytest.mark.asyncio
async def test_pasteee_401_without_key_hints_env():
    a = PasteEEAdapter(
        client=_client(
            [httpx.Response(401, json={"success": False, "errors": [{"code": 1}]})]
        ),
    )
    with pytest.raises(MemoryAdapterError, match="PASTE_EE_API_KEY"):
        await a.put(Artifact(content=b"x", mime="text/plain"))
    a = PasteEEAdapter(
        client=_client([httpx.Response(200, json={"success": False})])
    )
    with pytest.raises(MemoryAdapterError):
        await a.put(Artifact(content=b"x"))


# ---------------------------------------------------------------------------
# TermbinAdapter (asyncio.open_connection is monkeypatched)
# ---------------------------------------------------------------------------

class _FakeWriter:
    def __init__(self) -> None:
        self.buf = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buf += data

    def write_eof(self) -> None:
        pass

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeReader:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def read(self, _n: int) -> bytes:
        return self._payload


@pytest.mark.asyncio
async def test_termbin_put_get_roundtrip(monkeypatch: Any):
    content = b"termbin"
    envelope = _envelope(content)

    async def fake_open(host, port):
        return _FakeReader(b"https://termbin.com/abcde\n"), _FakeWriter()

    monkeypatch.setattr("asyncio.open_connection", fake_open)

    dl = httpx.Response(200, content=envelope)
    a = TermbinAdapter(client=_client([dl]))
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:termbin:https://termbin.com/abcde"

    art = await a.get(ref)
    assert art.content == content


@pytest.mark.asyncio
async def test_termbin_put_bad_response_raises(monkeypatch: Any):
    async def fake_open(host, port):
        return _FakeReader(b"not-a-url"), _FakeWriter()

    monkeypatch.setattr("asyncio.open_connection", fake_open)
    with pytest.raises(MemoryAdapterError):
        await TermbinAdapter().put(Artifact(content=b"x"))


# ---------------------------------------------------------------------------
# TmpFilesAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tmpfiles_put_get_roundtrip():
    content = b"tmpfiles"
    envelope = _envelope(content)
    up = httpx.Response(
        200,
        json={
            "status": "success",
            "data": {"url": "https://tmpfiles.org/123/file.json"},
        },
    )
    dl = httpx.Response(200, content=envelope)
    a = TmpFilesAdapter(client=_client([up, dl]))
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:tmpfiles:https://tmpfiles.org/dl/123/file.json"
    art = await a.get(ref)
    assert art.content == content


@pytest.mark.asyncio
async def test_tmpfiles_put_failure_raises():
    a = TmpFilesAdapter(
        client=_client([httpx.Response(200, json={"status": "error"})])
    )
    with pytest.raises(MemoryAdapterError):
        await a.put(Artifact(content=b"x"))


# ---------------------------------------------------------------------------
# TransferShAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transfersh_put_get_roundtrip():
    content = b"transfer"
    envelope = _envelope(content)
    up = httpx.Response(200, text="https://transfer.sh/abcd/file.json\n")
    dl = httpx.Response(200, content=envelope)
    a = TransferShAdapter(client=_client([up, dl]))
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:transfersh:https://transfer.sh/abcd/file.json"
    art = await a.get(ref)
    assert art.content == content


@pytest.mark.asyncio
async def test_transfersh_put_failure_raises():
    a = TransferShAdapter(client=_client([httpx.Response(500, text="boom")]))
    with pytest.raises(MemoryAdapterError):
        await a.put(Artifact(content=b"x"))


# ---------------------------------------------------------------------------
# SprungeAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sprunge_put_get_roundtrip():
    content = b"sprunge"
    envelope = _envelope(content)
    up = httpx.Response(200, text="http://sprunge.us/XyZ12\n")
    dl = httpx.Response(200, content=envelope)
    a = SprungeAdapter(client=_client([up, dl]))
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:sprunge:XyZ12"
    art = await a.get(ref)
    assert art.content == content


# ---------------------------------------------------------------------------
# PasteRsAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pasters_put_get_roundtrip():
    content = b"paste.rs"
    envelope = _envelope(content)
    up = httpx.Response(201, text="https://paste.rs/abc\n")
    dl = httpx.Response(200, content=envelope)
    a = PasteRsAdapter(client=_client([up, dl]))
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:pasters:abc"
    art = await a.get(ref)
    assert art.content == content


# ---------------------------------------------------------------------------
# HastebinAdapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hastebin_put_get_roundtrip():
    content = b"haste"
    envelope = _envelope(content)
    up = httpx.Response(200, json={"key": "ABCDE"})
    dl = httpx.Response(200, content=envelope)
    a = HastebinAdapter(client=_client([up, dl]))
    ref = await a.put(Artifact(content=content, mime="text/plain"))
    assert ref == "ref:hastebin:ABCDE"
    art = await a.get(ref)
    assert art.content == content


@pytest.mark.asyncio
async def test_hastebin_get_404_raises():
    a = HastebinAdapter(client=_client([httpx.Response(404)]))
    with pytest.raises(RefNotFoundError):
        await a.get("ref:hastebin:gone")


# ---------------------------------------------------------------------------
# Factory integration: all 14 cloud schemes wire up
# ---------------------------------------------------------------------------

def test_factory_registers_all_cloud_adapters(tmp_path):
    """build_memory_port should attach every adapter requested in config."""
    from swarm.memory.factory import build_memory_port

    class _FakeDM:
        _node_id = "fake"

    cfg = {
        "memory_facade": {
            "enabled": True,
            "scratch_root": str(tmp_path / "scratch"),
            "cloud_paste": {
                "nullpointer": True,
                "catbox": True,
                "fileio": True,
                "dpaste": True,
                "ixio": True,
                "telegraph": True,
                "rentry": True,
                "pasteee": True,
                "termbin": True,
                "tmpfiles": True,
                "transfersh": True,
                "sprunge": True,
                "pasters": True,
                "hastebin": True,
            },
        }
    }
    port = build_memory_port(cfg, _FakeDM())
    assert port is not None
    caps = port.capabilities()
    for scheme in [
        "file",
        "swarm",
        "nullpointer",
        "catbox",
        "fileio",
        "dpaste",
        "ixio",
        "telegraph",
        "rentry",
        "pasteee",
        "termbin",
        "tmpfiles",
        "transfersh",
        "sprunge",
        "pasters",
        "hastebin",
    ]:
        assert scheme in caps.schemes, f"missing {scheme!r} adapter"
