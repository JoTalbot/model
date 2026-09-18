"""Tests for paste HTTP fetch allowlist / SSRF guard."""

from __future__ import annotations

import httpx
import pytest

from swarm.memory.http_fetch_guard import (
    BUILTIN_FETCH_HOSTS,
    GuardedHttpxClient,
    assert_http_fetch_allowed,
    http_link_allowlist_from_memory_facade,
    resolve_allowed_hosts_from_cloud_paste_cfg,
)
from swarm.memory.types import MemoryAdapterError


def test_http_link_allowlist_disabled_returns_none():
    assert http_link_allowlist_from_memory_facade({}) is None
    assert http_link_allowlist_from_memory_facade({"http_links": {}}) is None
    assert (
        http_link_allowlist_from_memory_facade({"http_links": {"enabled": False}})
        is None
    )


def test_http_link_allowlist_requires_hosts_when_enabled():
    with pytest.raises(MemoryAdapterError, match="allowlist is empty"):
        http_link_allowlist_from_memory_facade(
            {"http_links": {"enabled": True, "allowlist": []}}
        )


def test_http_link_allowlist_returns_frozenset():
    h = http_link_allowlist_from_memory_facade(
        {"http_links": {"enabled": True, "allowlist": ["Example.COM", "x.org"]}}
    )
    assert h == frozenset({"example.com", "x.org"})


def test_builtin_contains_core_paste_hosts():
    assert "0x0.st" in BUILTIN_FETCH_HOSTS
    assert "files.catbox.moe" in BUILTIN_FETCH_HOSTS
    assert "api.telegra.ph" in BUILTIN_FETCH_HOSTS


def test_assert_blocks_private_ipv4():
    with pytest.raises(MemoryAdapterError, match="disallowed address"):
        assert_http_fetch_allowed("http://127.0.0.1/", BUILTIN_FETCH_HOSTS)


def test_assert_blocks_literal_public_ip():
    with pytest.raises(MemoryAdapterError, match="literal IP"):
        assert_http_fetch_allowed("http://8.8.8.8/", BUILTIN_FETCH_HOSTS)


def test_assert_blocks_unknown_host():
    with pytest.raises(MemoryAdapterError, match="not in allowlist"):
        assert_http_fetch_allowed("https://evil.example/x", BUILTIN_FETCH_HOSTS)


def test_assert_allows_builtin_host():
    assert_http_fetch_allowed("https://0x0.st/abc", BUILTIN_FETCH_HOSTS) is None


def test_resolve_explicit_allowlist_replaces_builtin():
    cfg = {"http_fetch_allowlist": ["example.com"]}
    hosts = resolve_allowed_hosts_from_cloud_paste_cfg(cfg)
    assert hosts == frozenset({"example.com"})
    assert_http_fetch_allowed("https://example.com/p", hosts) is None
    with pytest.raises(MemoryAdapterError):
        assert_http_fetch_allowed("https://0x0.st/x", hosts)


def test_resolve_extra_merges_with_default():
    cfg = {"http_fetch_allowlist_extra": ["mirror.example.org"]}
    hosts = resolve_allowed_hosts_from_cloud_paste_cfg(cfg)
    assert "0x0.st" in hosts
    assert "mirror.example.org" in hosts


@pytest.mark.asyncio
async def test_guarded_client_blocks_before_inner():
    inner = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"ok"))
    )
    client = GuardedHttpxClient(inner, frozenset({"safe.example"}))
    with pytest.raises(MemoryAdapterError):
        await client.get("https://0x0.st/x")
    await inner.aclose()
