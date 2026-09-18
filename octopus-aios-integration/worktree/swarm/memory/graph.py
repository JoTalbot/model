"""Graph builders + renderers for swarm memory visualisation.

Three graph sources are supported out of the box:

* :func:`build_wiki_graph`     — Obsidian vault note ↔ wiki-link graph.
* :func:`build_metrics_graph`  — adapter-scheme hub with availability /
  latency annotations.  Useful for spotting unhealthy backends.
* :func:`build_repository_graph` — table → record nodes, edges by shared
  tag.  Reveals natural clusters across the swarm's knowledge.

Renderers emit Graphviz DOT, Mermaid (flowchart) and plain JSON.  All
renderers are pure functions with zero external dependencies — the
graphs render anywhere a text file does, which is the whole point in
disaster-recovery scenarios.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphNode:
    id: str
    label: str = ""
    kind: str = "node"
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    src: str
    dst: str
    label: str = ""
    weight: float = 1.0


@dataclass
class MemoryGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}

    def add_node(self, node: GraphNode) -> None:
        if any(n.id == node.id for n in self.nodes):
            return
        self.nodes.append(node)

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_wiki_graph(obsidian_adapter) -> MemoryGraph:
    """Build a graph from an ``ObsidianVaultAdapter`` instance."""
    g = MemoryGraph()
    structure = obsidian_adapter.graph()
    # Add concrete notes
    for slug, info in structure.items():
        g.add_node(
            GraphNode(
                id=slug,
                label=info.get("title", slug),
                kind="note",
                attrs={"in_degree": len(info.get("in") or []), "out_degree": len(info.get("out") or [])},
            )
        )
    # Add dangling targets (referenced but not yet authored)
    existing = g.node_ids()
    for _slug, info in structure.items():
        for target in info.get("out") or []:
            if target not in existing:
                g.add_node(GraphNode(id=target, label=target, kind="missing"))
                existing.add(target)
    for slug, info in structure.items():
        for target in info.get("out") or []:
            g.add_edge(GraphEdge(src=slug, dst=target, label="links_to"))
    return g


def build_metrics_graph(metrics) -> MemoryGraph:
    """Hub-and-spoke graph: a virtual 'facade' connected to every scheme.

    Node attrs carry availability + p95 latency so renderers can colour-code.
    """
    g = MemoryGraph()
    g.add_node(GraphNode(id="__facade__", label="MemoryFacade", kind="hub"))
    snap = metrics.snapshot()
    for scheme, info in snap.items():
        g.add_node(
            GraphNode(
                id=scheme,
                label=scheme,
                kind="adapter",
                attrs=dict(info),
            )
        )
        g.add_edge(
            GraphEdge(
                src="__facade__",
                dst=scheme,
                label=f"avail={info['availability']:.0%}",
                weight=max(0.05, float(info["availability"])),
            )
        )
    return g


def build_repository_graph(rows: Iterable, *, max_per_table: int = 50) -> MemoryGraph:
    """Build a graph from :class:`MemoryRepository` rows.

    Nodes:
      * one per *table*  (kind="table")
      * one per *record* (kind="record") capped at ``max_per_table``
    Edges:
      * table → record   (kind="contains")
      * record ↔ record  if they share at least one non-``table:*`` tag.
    """
    g = MemoryGraph()
    by_table: dict[str, list[Any]] = {}
    for row in rows:
        by_table.setdefault(row.table or "_unknown", []).append(row)

    for table, items in by_table.items():
        tid = f"table:{table}"
        g.add_node(GraphNode(id=tid, label=table, kind="table",
                             attrs={"count": len(items)}))
        for row in items[:max_per_table]:
            rid = row.ref
            short = (
                (row.data.get("title") if isinstance(row.data, dict) else None)
                or rid.split(":")[-1][:8]
            )
            g.add_node(
                GraphNode(
                    id=rid,
                    label=str(short),
                    kind="record",
                    attrs={"tags": row.tags, "table": row.table},
                )
            )
            g.add_edge(GraphEdge(src=tid, dst=rid, label="contains"))

    # Tag co-occurrence edges: skip 'table:*' which would re-state above.
    by_tag: dict[str, list[str]] = {}
    for _table, items in by_table.items():
        for row in items[:max_per_table]:
            for t in row.tags or []:
                if t.startswith("table:"):
                    continue
                by_tag.setdefault(t, []).append(row.ref)
    for tag, refs in by_tag.items():
        if len(refs) < 2:
            continue
        first = refs[0]
        for other in refs[1:]:
            g.add_edge(GraphEdge(src=first, dst=other, label=f"tag:{tag}"))

    return g


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def to_json(graph: MemoryGraph) -> str:
    return json.dumps(
        {
            "nodes": [
                {"id": n.id, "label": n.label, "kind": n.kind, "attrs": n.attrs}
                for n in graph.nodes
            ],
            "edges": [
                {"src": e.src, "dst": e.dst, "label": e.label, "weight": e.weight}
                for e in graph.edges
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _dot_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def to_dot(graph: MemoryGraph, *, name: str = "memory") -> str:
    lines: list[str] = [f"digraph {name} {{", "  rankdir=LR;"]
    for n in graph.nodes:
        shape = {
            "table": "folder",
            "record": "note",
            "note": "box",
            "missing": "box, style=dashed",
            "hub": "doubleoctagon",
            "adapter": "ellipse",
        }.get(n.kind, "ellipse")
        attrs = []
        if "availability" in n.attrs:
            attrs.append(f"avail={n.attrs['availability']}")
        if "count" in n.attrs:
            attrs.append(f"n={n.attrs['count']}")
        if "in_degree" in n.attrs:
            attrs.append(f"in={n.attrs['in_degree']} out={n.attrs['out_degree']}")
        suffix = "\\n" + " ".join(attrs) if attrs else ""
        lines.append(
            f'  "{_dot_escape(n.id)}" [label="{_dot_escape(n.label + suffix)}", shape={shape}];'
        )
    for e in graph.edges:
        lab = f' [label="{_dot_escape(e.label)}"]' if e.label else ""
        lines.append(f'  "{_dot_escape(e.src)}" -> "{_dot_escape(e.dst)}"{lab};')
    lines.append("}")
    return "\n".join(lines)


def _mermaid_id(s: str) -> str:
    # Mermaid node IDs must be [A-Za-z0-9_]; escape via stable hash-style prefix.
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in s)
    if not safe or not safe[0].isalpha():
        safe = "n_" + safe
    return safe[:64]


def to_mermaid(graph: MemoryGraph) -> str:
    lines: list[str] = ["flowchart LR"]
    seen: dict[str, str] = {}
    for n in graph.nodes:
        mid = _mermaid_id(n.id)
        # avoid id collisions across kinds
        candidate = mid
        i = 1
        while candidate in seen.values():
            candidate = f"{mid}_{i}"
            i += 1
        seen[n.id] = candidate
        label = n.label.replace('"', "'")
        if n.kind == "table":
            marker = f'[[{label}]]'
        elif n.kind == "missing":
            marker = f'>"{label}"]'
        elif n.kind in {"record", "note"}:
            marker = f'(("{label}"))'
        elif n.kind == "hub":
            marker = f'[["{label}"]]'
        else:
            marker = f'["{label}"]'
        lines.append(f"    {candidate}{marker}")
    for e in graph.edges:
        src = seen.get(e.src, _mermaid_id(e.src))
        dst = seen.get(e.dst, _mermaid_id(e.dst))
        if e.label:
            lab = e.label.replace('"', "'")
            lines.append(f'    {src} -- "{lab}" --> {dst}')
        else:
            lines.append(f"    {src} --> {dst}")
    return "\n".join(lines)


def to_ascii(graph: MemoryGraph) -> str:
    """Plain-text rendering for shells that can't open SVG."""
    by_src: dict[str, list[GraphEdge]] = {}
    for e in graph.edges:
        by_src.setdefault(e.src, []).append(e)
    labels = {n.id: n.label or n.id for n in graph.nodes}
    out: list[str] = []
    out.append(f"nodes={len(graph.nodes)} edges={len(graph.edges)}")
    for n in graph.nodes:
        out.append(f"* [{n.kind}] {n.id}  ({n.label})")
        for e in by_src.get(n.id, []):
            tgt = labels.get(e.dst, e.dst)
            arrow = f"   --{e.label}-->" if e.label else "   -->"
            out.append(f"  {arrow} {e.dst}  ({tgt})")
    return "\n".join(out)
