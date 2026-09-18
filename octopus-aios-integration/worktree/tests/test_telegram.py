"""Tests for swarm.memory.telegram -- tiny long-polling bot."""

from __future__ import annotations

import json

import httpx
import pytest

from swarm.memory.port import MemoryMetrics
from swarm.memory.repository import MemoryRepository
from swarm.memory.telegram import (
    BotConfig,
    TelegramBot,
    format_status,
    parse_insert_args,
)
from swarm.memory.types import Artifact, Capabilities, RefMeta

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_insert_args_basic():
    table, data = parse_insert_args("notes a=1 b=hello")
    assert table == "notes"
    assert data == {"a": 1, "b": "hello"}


def test_parse_insert_args_coerces_int_float_bool_null():
    _, data = parse_insert_args("t i=42 f=3.14 ok=true bad=false nil=null s=foo")
    assert data == {
        "i": 42,
        "f": 3.14,
        "ok": True,
        "bad": False,
        "nil": None,
        "s": "foo",
    }


def test_parse_insert_args_handles_quoted_values():
    _, data = parse_insert_args('t name="Vasya Pupkin" city=msk')
    assert data == {"name": "Vasya Pupkin", "city": "msk"}


def test_parse_insert_args_requires_equals():
    with pytest.raises(ValueError, match="missing '='"):
        parse_insert_args("notes badfragment")


def test_parse_insert_args_empty_raises():
    with pytest.raises(ValueError):
        parse_insert_args("")


def test_format_status_empty():
    text = format_status({})
    assert "No memory metrics" in text


def test_format_status_with_metrics_and_audit():
    snap = {
        "catbox": {
            "puts": 3, "gets_ok": 2, "gets_err": 1, "availability": 0.67,
        },
        "nullpointer": {
            "puts": 1, "gets_ok": 1, "gets_err": 0, "availability": 1.0,
        },
    }
    text = format_status(
        snap,
        audit_stats={"total": 9, "per_op": {"put": 5, "get": 4}},
    )
    assert "catbox" in text
    assert "nullpointer" in text
    assert "Audit log" in text
    assert "9 events" in text


# ---------------------------------------------------------------------------
# Bot dispatch -- mock httpx for getUpdates / sendMessage
# ---------------------------------------------------------------------------


class _FakePort:
    def __init__(self) -> None:
        self._store: dict[str, Artifact] = {}
        self._metrics = MemoryMetrics()

    @property
    def metrics(self):
        return self._metrics

    def capabilities(self):
        return Capabilities(
            schemes=frozenset({"file"}),
            supports_search=True,
            supports_delete=True,
            supports_promote=False,
        )

    async def put(self, art: Artifact) -> str:
        ref = f"ref:file:{len(self._store)}"
        self._store[ref] = art
        return ref

    async def get(self, ref):
        return self._store[ref]

    async def exists(self, ref):
        return ref in self._store

    async def delete(self, ref):
        return self._store.pop(ref, None) is not None

    async def search(self, tags, owner=None):
        return [
            RefMeta(ref=r, scheme="file", tags=list(a.tags))
            for r, a in self._store.items()
            if all(t in (a.tags or []) for t in (tags or []))
        ]


def _mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)


async def test_bot_send_includes_chat_id_and_text():
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        captured.append((str(req.url), body))
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot(
        BotConfig(token="TEST"),
        client=_mock_client(handler),
        metrics=MemoryMetrics(),
    )
    await bot.send(42, "hello world")
    assert captured
    url, body = captured[0]
    assert "/botTEST/sendMessage" in url
    assert body["chat_id"] == 42
    assert body["text"] == "hello world"


async def test_bot_dispatch_status_replies_with_metrics():
    metrics = MemoryMetrics()
    metrics.record_put("catbox")
    metrics.record_get("catbox", ok=True)
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={42}),
        client=_mock_client(handler),
        metrics=metrics,
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 42}, "text": "/status"},
    }
    await bot._dispatch(update)
    assert sent
    assert "catbox" in sent[0]["text"]


async def test_bot_dispatch_ignores_disallowed_chat():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={42}),
        client=_mock_client(handler),
        metrics=MemoryMetrics(),
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 9999}, "text": "/status"},
    }
    await bot._dispatch(update)
    assert sent == []


async def test_bot_dispatch_denies_empty_allowlist_without_open_access():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids=set(), open_access=False),
        client=_mock_client(handler),
        metrics=MemoryMetrics(),
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "text": "/status"},
    }
    await bot._dispatch(update)
    assert sent == []


async def test_bot_dispatch_open_access_without_allowlist():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    metrics = MemoryMetrics()
    metrics.record_put("catbox")
    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids=set(), open_access=True),
        client=_mock_client(handler),
        metrics=metrics,
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 99}, "text": "/status"},
    }
    await bot._dispatch(update)
    assert sent
    assert "catbox" in sent[0]["text"]


async def test_bot_unknown_command_replies_helpful():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={1}),
        client=_mock_client(handler),
        metrics=MemoryMetrics(),
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "text": "/nope"},
    }
    await bot._dispatch(update)
    assert sent
    assert "unknown command" in sent[0]["text"]


async def test_bot_dispatch_insert_persists_row():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    port = _FakePort()
    repo = MemoryRepository(port)
    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={1}),
        client=_mock_client(handler),
        repository=repo,
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "text": "/insert notes title=zametka stars=5"},
    }
    await bot._dispatch(update)
    rows = await repo.query(table="notes")
    assert len(rows) == 1
    assert rows[0].data == {"title": "zametka", "stars": 5}
    assert "saved" in sent[0]["text"]


async def test_bot_dispatch_list_renders_latest():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    repo = MemoryRepository(_FakePort())
    await repo.save({"x": 1}, table="notes")
    await repo.save({"x": 2}, table="notes")

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={1}),
        client=_mock_client(handler),
        repository=repo,
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "text": "/list notes"},
    }
    await bot._dispatch(update)
    assert sent
    assert "latest" in sent[0]["text"]


async def test_bot_dispatch_qr_returns_monospace_block():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={1}),
        client=_mock_client(handler),
        metrics=MemoryMetrics(),
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "text": "/qr ref:catbox:short"},
    }
    await bot._dispatch(update)
    assert sent
    assert sent[0]["text"].startswith("```\n")


async def test_bot_dispatch_rag_uses_injected_callable():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    async def rag_fn(query: str) -> str:
        return f"RAG[{query}]"

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={1}),
        client=_mock_client(handler),
        rag_fn=rag_fn,
    )
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "text": "/rag what is alpha"},
    }
    await bot._dispatch(update)
    assert "RAG[what is alpha]" in sent[0]["text"]


async def test_bot_handles_handler_exception_gracefully():
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot(
        BotConfig(token="TEST", allowed_chat_ids={1}),
        client=_mock_client(handler),
        metrics=MemoryMetrics(),
    )
    # /insert without repo wired -> handler returns 'memory repository not wired'
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "text": "/insert"},
    }
    await bot._dispatch(update)
    assert sent
    assert "not wired" in sent[0]["text"] or "error" in sent[0]["text"]
