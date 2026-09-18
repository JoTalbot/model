"""
swarm/api/graph_endpoints.py
─────────────────────────────
Граф памяти Octopus (Obsidian-style) + типизация узлов.

Узлы графа:
  • file       — VFS-файл (table=vfs_files)
  • note       — заметка (table=notes / mime=text/plain)
  • tag        — тег (cluster)
  • node       — пир роя (NodeSnapshot)
  • task       — задача (Distributed Task Pool)
  • table      — логическая таблица в памяти

Рёбра:
  • file/note  ↔ tag        (HAS_TAG)
  • node       ↔ task       (ASSIGNED)
  • file/note  ↔ table      (BELONGS_TO)
  • file       ↔ file       (SAME_PATH)
  • node       ↔ node       (PEER, через handshake)
  • note       ↔ note       (WIKI_LINK [[link]])

Endpoints:
  GET /api/v1/memory/graph?scope=memory|swarm|all&max_nodes=200
  GET /api/v1/memory/types          ─ типы записей с counts
  GET /api/v1/memory/timeline?days=7 ─ записи по дням
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

_LOG = logging.getLogger("swarm.api.graph_endpoints")

_WIKI_LINK_RE = re.compile(r"\[\[([^\[\]\|]+)(?:\|[^\]]+)?\]\]")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _classify_record(row) -> tuple[str, str]:
    """Возвращает (kind, label) для записи."""
    data = getattr(row, "data", {}) or {}
    attrs = getattr(row, "attrs", {}) or {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(attrs, dict):
        attrs = {}
    table = getattr(row, "table", "") or attrs.get("_table") or ""

    if table == "vfs_files":
        return ("file", data.get("name") or "file")
    if table == "tasks":
        return ("task", str(data.get("description") or data.get("id") or "task")[:40])
    if table == "notes":
        return ("note", str(data.get("title") or data.get("name") or "note")[:40])
    if table == "files":
        return ("file", data.get("filename") or data.get("name") or "file")
    if "wiki" in str(table) or attrs.get("kind") == "wiki":
        return ("wiki", str(data.get("title") or "wiki")[:40])
    label = attrs.get("title") or data.get("title") or data.get("name") or data.get("content", "")[:40]
    return ("record", str(label)[:40] or table or "record")


# ──────────────────── /api/v1/memory/graph ──────────────────────────────────

def handle_memory_graph(container, scope: str = "all", max_nodes: int = 250) -> dict:
    """
    Строит граф связей записей в памяти.

    scope = memory: только записи + теги
    scope = swarm:  ноды роя + задачи + связи
    scope = all:    всё вместе
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()

    def add_node(nid: str, label: str, kind: str, **extra) -> None:
        if nid in seen_ids:
            return
        seen_ids.add(nid)
        nodes.append({"id": nid, "label": label, "kind": kind, **extra})

    def add_edge(src: str, dst: str, kind: str = "rel", weight: float = 1.0) -> None:
        edges.append({"src": src, "dst": dst, "kind": kind, "weight": weight})

    try:
        # ─── Записи памяти ─────────────────────────────────────────────────
        if scope in ("memory", "all"):
            from swarm.memory.repository import MemoryRepository
            mp = container.agent.memory_port if container.agent else None
            if mp is not None:
                repo = MemoryRepository(mp)

                async def _q():
                    return await repo.latest(n=max_nodes)
                rows = _run(_q())

                tables_seen: dict[str, int] = {}
                tags_seen: dict[str, int] = {}
                paths_seen: dict[str, list[str]] = {}
                wiki_titles: dict[str, str] = {}  # title→record_id для wiki-link

                for r in rows:
                    kind, label = _classify_record(r)
                    rid = "rec:" + (getattr(r, "ref", "") or str(id(r)))
                    add_node(rid, label, kind,
                             table=getattr(r, "table", ""),
                             ref=getattr(r, "ref", ""))

                    # Tag-кластеры
                    for t in (getattr(r, "tags", None) or []):
                        if t.startswith("table:"):
                            continue
                        tid = "tag:" + t
                        add_node(tid, "#" + t, "tag")
                        add_edge(rid, tid, "HAS_TAG", weight=0.6)
                        tags_seen[t] = tags_seen.get(t, 0) + 1

                    # Table-узлы
                    tbl = getattr(r, "table", "") or ""
                    if tbl:
                        ttid = "table:" + tbl
                        add_node(ttid, "▣ " + tbl, "table", count=tables_seen.get(tbl, 0) + 1)
                        add_edge(rid, ttid, "BELONGS_TO", weight=0.4)
                        tables_seen[tbl] = tables_seen.get(tbl, 0) + 1

                    # SAME_PATH для VFS-файлов
                    attrs = getattr(r, "attrs", {}) or {}
                    if isinstance(attrs, dict):
                        p = attrs.get("path", "") or ""
                        if p:
                            paths_seen.setdefault(p, []).append(rid)

                    # WIKI-связи (для note/wiki): [[title]]
                    data = getattr(r, "data", {}) or {}
                    if isinstance(data, dict):
                        title = data.get("title")
                        if title:
                            wiki_titles[title.strip().lower()] = rid

                # Дорисовываем SAME_PATH
                for p, ids in paths_seen.items():
                    if len(ids) < 2 or len(ids) > 10:
                        continue
                    for a in ids:
                        for b in ids:
                            if a < b:
                                add_edge(a, b, "SAME_PATH", weight=0.3)

                # WIKI-связи [[link]] на основе текста
                for r in rows:
                    data = getattr(r, "data", {}) or {}
                    if not isinstance(data, dict):
                        continue
                    text = " ".join([
                        str(data.get("content") or ""),
                        str(data.get("text") or ""),
                        str(data.get("note") or ""),
                    ])
                    if not text:
                        continue
                    rid = "rec:" + (getattr(r, "ref", "") or str(id(r)))
                    for m in _WIKI_LINK_RE.finditer(text):
                        target = m.group(1).strip().lower()
                        target_id = wiki_titles.get(target)
                        if target_id and target_id != rid:
                            add_edge(rid, target_id, "WIKI_LINK", weight=1.2)

        # ─── Рой ─────────────────────────────────────────────────────────────
        if scope in ("swarm", "all"):
            node_self = getattr(container, "node_self", None)
            self_id = getattr(container.kad, "node_id", "") or "self"
            add_node("node:" + self_id, "ME · " + self_id[:8], "node_self", is_self=True)

            if node_self is not None:
                try:
                    swarm_map = node_self.swarm_map()
                    for nid, snap in swarm_map.items():
                        if nid == self_id:
                            continue
                        nid_label = nid[:8]
                        add_node("node:" + nid, "node " + nid_label, "node",
                                 health=getattr(snap, "health", "?"),
                                 role=getattr(snap, "role", "?"))
                        add_edge("node:" + self_id, "node:" + nid, "PEER", weight=2.0)
                except Exception:
                    pass

            # Handshake пиры (verified)
            registry = getattr(container, "peer_registry", None)
            if registry is not None:
                try:
                    for p in registry.all_peers():
                        nid = "node:" + p.node_id
                        add_node(nid, "✓ " + p.node_id[:8], "node_verified")
                        add_edge("node:" + self_id, nid, "VERIFIED", weight=2.5)
                except Exception:
                    pass

            # Kademlia пиры
            try:
                kad_peers = []
                kad = container.kad
                if hasattr(kad, "protocol") and kad.protocol:
                    rt = getattr(kad.protocol, "router", None)
                    if rt and hasattr(rt, "find_neighbors"):
                        kad_peers = rt.find_neighbors(getattr(kad, "node", None) or kad, exclude=None)
                for p in (kad_peers or [])[:20]:
                    pid = getattr(p, "id", None) or getattr(p, "node_id", None) or str(p)
                    pid_hex = pid.hex() if isinstance(pid, bytes) else str(pid)
                    nid = "node:kad:" + pid_hex[:12]
                    add_node(nid, "kad " + pid_hex[:8], "node_kad")
                    add_edge("node:" + self_id, nid, "KAD", weight=0.8)
            except Exception:
                pass

            # Tasks
            try:
                agent = container.agent
                if agent is not None and hasattr(agent, "task_pool"):
                    pool = agent.task_pool
                    tasks = list(getattr(pool, "_tasks", {}).values())[:40]
                    for t in tasks:
                        tid = "task:" + getattr(t, "id", str(id(t)))
                        add_node(tid, "✓ " + str(getattr(t, "description", "task"))[:30], "task",
                                 status=getattr(t, "status", "?"))
                        assigned = getattr(t, "assigned_to", None)
                        if assigned:
                            add_edge("node:" + assigned, tid, "ASSIGNED", weight=1.4)
                        else:
                            add_edge("node:" + self_id, tid, "OWNS", weight=0.7)
            except Exception:
                pass

        # лимит
        if len(nodes) > max_nodes:
            keep = set(n["id"] for n in nodes[:max_nodes])
            nodes = [n for n in nodes if n["id"] in keep]
            edges = [e for e in edges if e["src"] in keep and e["dst"] in keep]

        return {"ok": True, "nodes": nodes, "edges": edges,
                "stats": {"nodes": len(nodes), "edges": len(edges)}}
    except Exception as exc:
        _LOG.exception("memory_graph failed")
        return {"ok": False, "error": str(exc), "nodes": nodes, "edges": edges}


# ──────────────────── /api/v1/memory/types ──────────────────────────────────

def handle_memory_types(container) -> dict:
    """Сводка типов записей с количеством."""
    try:
        from swarm.memory.repository import MemoryRepository
        mp = container.agent.memory_port if container.agent else None
        if mp is None:
            return {"ok": False, "types": [], "error": "no memory_port"}
        repo = MemoryRepository(mp)

        async def _q():
            return await repo.latest(n=10000)
        rows = _run(_q())

        by_table: dict[str, dict] = {}
        by_kind: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        by_mime: dict[str, int] = {}
        ts_min = float("inf")
        ts_max = 0.0
        total_bytes = 0
        for r in rows:
            kind, _ = _classify_record(r)
            tbl = getattr(r, "table", "") or "unknown"
            data = getattr(r, "data", {}) or {}
            attrs = getattr(r, "attrs", {}) or {}
            if not isinstance(data, dict):
                data = {}
            if not isinstance(attrs, dict):
                attrs = {}
            by_table.setdefault(tbl, {"count": 0, "size": 0, "kind": kind})
            by_table[tbl]["count"] += 1
            sz = int(data.get("size") or 0)
            by_table[tbl]["size"] += sz
            total_bytes += sz
            by_kind[kind] = by_kind.get(kind, 0) + 1
            mime = data.get("mime") or "text/plain"
            by_mime[mime] = by_mime.get(mime, 0) + 1
            for t in (getattr(r, "tags", None) or []):
                if t.startswith("table:"):
                    continue
                by_tag[t] = by_tag.get(t, 0) + 1
            ts = attrs.get("_ts") or 0
            if ts:
                ts_min = min(ts_min, ts)
                ts_max = max(ts_max, ts)

        types = [
            {"table": k, "count": v["count"], "size": v["size"], "kind": v["kind"]}
            for k, v in sorted(by_table.items(), key=lambda x: -x[1]["count"])
        ]
        top_tags = sorted(by_tag.items(), key=lambda x: -x[1])[:30]

        return {
            "ok": True,
            "types":         types,
            "by_kind":       by_kind,
            "by_mime":       by_mime,
            "top_tags":      [{"tag": k, "count": v} for k, v in top_tags],
            "total_records": len(rows),
            "total_bytes":   total_bytes,
            "ts_min":        ts_min if ts_min != float("inf") else None,
            "ts_max":        ts_max or None,
        }
    except Exception as exc:
        _LOG.exception("memory_types failed")
        return {"ok": False, "error": str(exc), "types": []}


# ──────────────────── /api/v1/memory/timeline ────────────────────────────────

def handle_memory_timeline(container, days: int = 7) -> dict:
    """Записи по дням за последние N дней (для линии тренда)."""
    try:
        from swarm.memory.repository import MemoryRepository
        mp = container.agent.memory_port if container.agent else None
        if mp is None:
            return {"ok": False, "timeline": [], "error": "no memory_port"}
        repo = MemoryRepository(mp)

        async def _q():
            return await repo.latest(n=10000)
        rows = _run(_q())

        now = time.time()
        cutoff = now - days * 86400
        buckets: dict[str, dict] = {}
        for r in rows:
            attrs = getattr(r, "attrs", {}) or {}
            if not isinstance(attrs, dict):
                continue
            ts = attrs.get("_ts") or 0
            if ts < cutoff:
                continue
            kind, _ = _classify_record(r)
            day = time.strftime("%Y-%m-%d", time.gmtime(ts))
            b = buckets.setdefault(day, {"total": 0, "by_kind": {}})
            b["total"] += 1
            b["by_kind"][kind] = b["by_kind"].get(kind, 0) + 1

        # Заполняем пустые дни
        timeline = []
        for i in range(days, -1, -1):
            day = time.strftime("%Y-%m-%d", time.gmtime(now - i * 86400))
            b = buckets.get(day, {"total": 0, "by_kind": {}})
            timeline.append({"day": day, "total": b["total"], "by_kind": b["by_kind"]})
        return {"ok": True, "timeline": timeline, "days": days}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "timeline": []}


# ──────────────────── /api/v1/swarm/processes ────────────────────────────────

def handle_swarm_processes(container) -> dict:
    """
    Активные процессы внутри ноды + рой. Для наглядной анимации в UI.
    """
    out = {
        "ok": True,
        "ts": time.time(),
        "node_id": "",
        "uptime_sec": 0,
        "processes": [],     # активные внутренние процессы / loops
        "queues": {},        # размеры очередей
        "rates": {},         # gossip_rx/sec, tasks/sec и т.п.
        "swarm_health": "?",
        "peers": {"kad": 0, "verified": 0, "swarm_map": 0},
    }
    try:
        out["node_id"] = getattr(container.kad, "node_id", "") or "unknown"

        # NodeSelf
        ns = getattr(container, "node_self", None)
        if ns is not None:
            try:
                snap = ns.snapshot()
                out["uptime_sec"] = snap.uptime_sec
                out["role"] = snap.role
                out["skills"] = [s.get("name") if isinstance(s, dict) else getattr(s, "name", "?") for s in (snap.skills or [])]
                out["health"] = snap.health
                out["health_score"] = snap.health_score
                out["load"] = snap.load
                out["peers"]["swarm_map"] = len(ns.swarm_map())
            except Exception:
                pass

        # Gossip
        try:
            out["gossip"] = container.gossip.stats()
        except Exception:
            pass

        # RPC server stats
        try:
            rpc = container.rpc_server
            if hasattr(rpc, "stats"):
                out["rpc"] = rpc.stats()
        except Exception:
            pass

        # Verified peers
        reg = getattr(container, "peer_registry", None)
        if reg is not None:
            try:
                out["peers"]["verified"] = len(reg)
            except Exception:
                pass

        # Тасковый пул
        try:
            agent = container.agent
            pool = getattr(agent, "task_pool", None)
            if pool:
                tasks = list(getattr(pool, "_tasks", {}).values())
                from collections import Counter
                statuses = Counter(getattr(t, "status", "?") for t in tasks)
                out["queues"]["tasks"] = dict(statuses)
                out["queues"]["tasks_total"] = len(tasks)
        except Exception:
            pass

        # Сам процесс — asyncio tasks
        try:
            current_loop_tasks = []
            for t in asyncio.all_tasks():
                name = t.get_name() or repr(t)
                current_loop_tasks.append(name[:50])
            # дедуп
            from collections import Counter
            cnt = Counter(current_loop_tasks)
            out["processes"] = [
                {"name": n, "count": c, "kind": _process_kind(n)}
                for n, c in cnt.most_common(50)
            ]
        except Exception:
            # Эта корутина вызывается из sync-контекста (HTTP handler),
            # поэтому asyncio.all_tasks() кинет — это норма.
            pass

        return out
    except Exception as exc:
        _LOG.exception("swarm_processes failed")
        return {"ok": False, "error": str(exc)}


def _process_kind(name: str) -> str:
    n = name.lower()
    if "gossip" in n: return "gossip"
    if "kad" in n or "kademlia" in n: return "kademlia"
    if "rpc" in n: return "rpc"
    if "task" in n: return "task"
    if "sync" in n: return "sync"
    if "broadcast" in n or "awareness" in n: return "awareness"
    if "repair" in n: return "repair"
    if "sse" in n or "stream" in n: return "stream"
    return "other"
