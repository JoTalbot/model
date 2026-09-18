"""Graph builders + renderers tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.adapters.obsidian import ObsidianVaultAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.graph import (
    GraphEdge,
    GraphNode,
    MemoryGraph,
    build_metrics_graph,
    build_repository_graph,
    build_wiki_graph,
    to_ascii,
    to_dot,
    to_json,
    to_mermaid,
)
from swarm.memory.port import MemoryMetrics
from swarm.memory.repository import MemoryRepository
from swarm.memory.types import Artifact

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_wiki_graph_from_obsidian(tmp_path: Path):
    vault = ObsidianVaultAdapter(tmp_path)
    await vault.put(Artifact(content="see [[Bravo]]", attrs={"title": "Alpha"}))
    await vault.put(Artifact(content="see [[Charlie]] and [[Ghost]]", attrs={"title": "Bravo"}))
    await vault.put(Artifact(content="dead-end", attrs={"title": "Charlie"}))

    g = build_wiki_graph(vault)
    ids = {n.id for n in g.nodes}
    assert {"alpha", "bravo", "charlie", "ghost"} <= ids
    # Ghost is referenced but not authored — must be marked 'missing'
    ghost = next(n for n in g.nodes if n.id == "ghost")
    assert ghost.kind == "missing"
    # Edges
    src_pairs = {(e.src, e.dst) for e in g.edges}
    assert ("alpha", "bravo") in src_pairs
    assert ("bravo", "ghost") in src_pairs


def test_build_metrics_graph_hub_and_spokes():
    m = MemoryMetrics()
    m.record_put("file")
    for _ in range(8):
        m.record_get("dpaste", ok=True)
    for _ in range(2):
        m.record_get("dpaste", ok=False)
    m.record_latency("dpaste", "get", 0.150)
    g = build_metrics_graph(m)
    ids = {n.id for n in g.nodes}
    assert "__facade__" in ids and "file" in ids and "dpaste" in ids
    dpaste = next(n for n in g.nodes if n.id == "dpaste")
    assert pytest.approx(dpaste.attrs["availability"], rel=1e-3) == 0.8


@pytest.mark.asyncio
async def test_build_repository_graph_tables_and_shared_tags(tmp_path: Path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)
    await repo.save({"title": "A"}, table="parts", tags=["windshield"])
    await repo.save({"title": "B"}, table="parts", tags=["windshield"])
    await repo.save({"title": "C"}, table="orders", tags=["windshield"])
    rows = await repo.query(limit=100)
    g = build_repository_graph(rows)
    ids = {n.id for n in g.nodes}
    assert "table:parts" in ids and "table:orders" in ids
    # 3 record nodes
    record_nodes = [n for n in g.nodes if n.kind == "record"]
    assert len(record_nodes) == 3
    # Tag-cooccurrence edges
    tag_edges = [e for e in g.edges if e.label.startswith("tag:windshield")]
    assert len(tag_edges) == 2  # 3 nodes share a tag => 2 chord edges from first


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _toy_graph() -> MemoryGraph:
    g = MemoryGraph()
    g.add_node(GraphNode(id="a", label="Alpha", kind="note"))
    g.add_node(GraphNode(id="b", label="Bravo", kind="note"))
    g.add_node(GraphNode(id="c", label="Charlie", kind="missing"))
    g.add_edge(GraphEdge(src="a", dst="b", label="links_to"))
    g.add_edge(GraphEdge(src="b", dst="c"))
    return g


def test_to_json_roundtrip():
    raw = to_json(_toy_graph())
    parsed = json.loads(raw)
    assert len(parsed["nodes"]) == 3
    assert len(parsed["edges"]) == 2


def test_to_dot_emits_directed_digraph():
    dot = to_dot(_toy_graph(), name="wiki")
    assert dot.startswith("digraph wiki {")
    assert "->" in dot
    assert 'shape=box' in dot or 'shape=box,' in dot or 'shape=box, ' in dot or 'shape=box;\n' in dot or 'shape=box;' in dot
    assert "missing" not in dot or "dashed" in dot


def test_to_mermaid_emits_flowchart_and_escapes_ids():
    src = to_mermaid(_toy_graph())
    assert src.startswith("flowchart LR")
    assert "-->" in src
    assert "Alpha" in src and "Bravo" in src and "Charlie" in src


def test_to_ascii_lists_nodes_and_edges():
    out = to_ascii(_toy_graph())
    assert "nodes=3 edges=2" in out
    assert "[note] a" in out
    assert "links_to" in out


def test_to_dot_quotes_special_chars():
    g = MemoryGraph()
    g.add_node(GraphNode(id='weird "id"', label='lbl "x"', kind="note"))
    dot = to_dot(g)
    # No raw double-quote inside the label braces — must be escaped.
    assert 'label="lbl \\"x\\""' in dot
