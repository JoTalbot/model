"""Tests for the Obsidian-flavoured Markdown vault adapter."""

from __future__ import annotations

import pytest

from swarm.memory.adapters.obsidian import (
    ObsidianVaultAdapter,
    extract_links,
    slugify,
)
from swarm.memory.types import Artifact, MemoryAdapterError, RefNotFoundError


def test_slugify_keeps_cyrillic_and_lowercases():
    assert slugify("Автостёкла LADA Granta!") == "автостёкла-lada-granta"


def test_slugify_collapses_punctuation():
    assert slugify("a / b * c") == "a-b-c"


def test_extract_links_basic_and_aliased():
    text = "see [[Alpha]] and [[Beta|the second one]] then [[Gamma]]"
    assert extract_links(text) == ["Alpha", "Beta", "Gamma"]


def test_extract_links_ignores_singles():
    assert extract_links("not a [link] here") == []


@pytest.mark.asyncio
async def test_obsidian_put_get_round_trip(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    art = Artifact(
        content="# Hello\nrefer to [[Other Note]]",
        tags=["wiki", "kb"],
        attrs={"title": "Hello", "author": "lisa"},
    )
    ref = await a.put(art)
    assert ref.startswith("ref:obsidian:hello")

    recovered = await a.get(ref)
    assert "[[Other Note]]" in recovered.content
    assert "wiki" in recovered.tags
    assert recovered.attrs.get("author") == "lisa"


@pytest.mark.asyncio
async def test_obsidian_disambiguates_duplicate_titles(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    r1 = await a.put(Artifact(content="v1", attrs={"title": "Same"}))
    r2 = await a.put(Artifact(content="v2", attrs={"title": "Same"}))
    assert r1 != r2
    assert (await a.get(r1)).content.strip() == "v1"
    assert (await a.get(r2)).content.strip() == "v2"


@pytest.mark.asyncio
async def test_obsidian_get_missing_raises(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    with pytest.raises(RefNotFoundError):
        await a.get("ref:obsidian:gone")


@pytest.mark.asyncio
async def test_obsidian_search_by_tag(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    await a.put(Artifact(content="x", tags=["kb"], attrs={"title": "A"}))
    await a.put(Artifact(content="y", tags=["scratch"], attrs={"title": "B"}))
    metas = await a.search(["kb"], None)
    assert len(metas) == 1
    assert metas[0].ref.endswith(":a")


@pytest.mark.asyncio
async def test_obsidian_delete_round_trip(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    ref = await a.put(Artifact(content="x", attrs={"title": "Trash"}))
    assert await a.exists(ref) is True
    assert await a.delete(ref) is True
    assert await a.exists(ref) is False
    assert await a.delete(ref) is False


@pytest.mark.asyncio
async def test_obsidian_rejects_path_traversal_slug(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    with pytest.raises(MemoryAdapterError):
        await a.get("ref:obsidian:../escape")


@pytest.mark.asyncio
async def test_obsidian_graph_and_backlinks(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    await a.put(Artifact(content="see [[Bravo]]", attrs={"title": "Alpha"}))
    await a.put(Artifact(content="see [[Alpha]] and [[Charlie]]", attrs={"title": "Bravo"}))
    await a.put(Artifact(content="no outgoing", attrs={"title": "Charlie"}))

    g = a.graph()
    assert "alpha" in g and "bravo" in g and "charlie" in g
    assert "bravo" in g["alpha"]["out"]
    # Backlinks
    assert "alpha" in g["bravo"]["in"]
    assert "bravo" in g["charlie"]["in"]
    assert a.backlinks("charlie") == ["bravo"]


@pytest.mark.asyncio
async def test_obsidian_links_resolve_via_slugify(tmp_path):
    a = ObsidianVaultAdapter(tmp_path)
    await a.put(Artifact(content="[[Авто стекло]]", attrs={"title": "Index"}))
    await a.put(Artifact(content="page body", attrs={"title": "Авто стекло"}))
    g = a.graph()
    assert "авто-стекло" in g["index"]["out"]
    assert "index" in g["авто-стекло"]["in"]


def test_factory_wires_obsidian_adapter(tmp_path):
    from swarm.memory.factory import build_memory_port

    class _FakeDM:
        _node_id = "fake"

    cfg = {
        "memory_facade": {
            "enabled": True,
            "scratch_root": str(tmp_path / "scratch"),
            "obsidian": {
                "enabled": True,
                "vault_root": str(tmp_path / "vault"),
            },
        }
    }
    port = build_memory_port(cfg, _FakeDM())
    assert port is not None
    assert "obsidian" in port.capabilities().schemes
