from __future__ import annotations
import time, asyncio, json, logging, io, uuid

_LOG = logging.getLogger("swarm.api.web_endpoints")

class _RebufferedRfile:
    def __init__(self, b): self._buf = io.BytesIO(b)
    def read(self, n=-1): return self._buf.read(n) if n is not None and n >= 0 else self._buf.read()
    def close(self): self._buf.close()
    def readable(self): return True
    def readline(self, n=-1): return self._buf.readline(n)

def _async_run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    if loop.is_running():
        new_loop = asyncio.new_event_loop()
        try: return new_loop.run_until_complete(coro)
        finally: new_loop.close()
    else:
        return loop.run_until_complete(coro)

def node_info_extended(container) -> dict:
    if container is None: return {"ok": True, "node_id": "standalone"}
    base = {"ok": True, "node_id": container.kad.node_id or "unknown", "port": container.port,
            "uptime_seconds": round(time.time() - getattr(container, "_started_at", time.time()), 1)}
    keys = getattr(container, "node_keys", None)
    registry = getattr(container, "peer_registry", None)
    base["auth"] = {"verified_peers": len(registry) if registry else 0, "pubkey": keys.public_key_hex() if keys else ""}
    if hasattr(container, "handshake_mgr"): base["handshake"] = container.handshake_mgr.stats()
    try: base["gossip"] = container.gossip.stats()
    except: pass
    return base

def handle_peer_list(container) -> dict:
    registry = getattr(container, "peer_registry", None)
    if registry is None: return {"ok": True, "peers": [], "count": 0}
    peers = [{"node_id": p.node_id, "address": p.address, "verified_at": p.verified_at} for p in registry.all_peers()]
    return {"ok": True, "peers": peers, "count": len(peers)}

def handle_memory_records(container, search: str = "", limit: int = 30) -> dict:
    from swarm.memory.repository import MemoryRepository
    try:
        mp = container.agent.memory_port
        if mp is None: return {"ok": False, "error": "no memory port"}
        repo = MemoryRepository(mp)
        rows = _async_run(repo.query(text=search, limit=limit) if search else repo.latest(n=limit))
        out = []
        for r in rows:
            data = r.data if isinstance(r.data, dict) else {}
            out.append({"ref": r.ref, "table": r.table, "title": r.attrs.get("title") or data.get("title", ""), "content": str(data.get("text") or data.get("content", ""))[:500], "tags": r.tags})
        return {"ok": True, "records": out, "count": len(out)}
    except Exception as e: return {"ok": False, "error": str(e)}

def handle_memory_ask(container, q: str) -> dict:
    if not q: return {"ok": False, "error": "empty query"}
    try:
        grag = getattr(container, "graph_rag", None)
        if grag is None: return {"ok": False, "error": "GraphRAG not initialized"}
        answer = _async_run(grag.query_with_graph(container.llm, q))
        return {"ok": True, "answer": answer, "query": q}
    except Exception as exc: return {"ok": False, "error": str(exc)}

def handle_knowledge_graph(container) -> dict:
    try:
        port = container.agent.memory_port
        obs = port._adapters.get('obsidian')
        if not obs: return {"ok": False, "error": "Obsidian adapter not found"}
        graph_data = obs.graph()
        nodes = [{"id": slug, "label": info["title"], "type": "note"} for slug, info in graph_data.items()]
        links = [{"source": slug, "target": t, "type": "wiki_link"} for slug, info in graph_data.items() for t in info["out"]]
        return {"ok": True, "nodes": nodes, "links": links}
    except Exception as exc: return {"ok": False, "error": str(exc)}

def handle_knowledge_note(container, slug: str) -> dict:
    try:
        from swarm.memory.ref_parse import make_ref
        obs = container.agent.memory_port._adapters.get('obsidian')
        if not obs: return {"ok": False, "error": "Obsidian adapter not found"}
        ref = make_ref("obsidian", slug)
        art = _async_run(obs.get(ref))
        return {"ok": True, "slug": slug, "title": art.attrs.get("title", slug), "content": art.content if isinstance(art.content, str) else art.content.decode("utf-8"), "tags": art.tags}
    except Exception as exc: return {"ok": False, "error": str(exc)}

def handle_llm_complete(container, body: dict) -> dict:
    messages = body.get("messages")
    model = body.get("model")
    if not messages: return {"ok": False, "error": "messages required"}
    try:
        if not container.llm: return {"ok": False, "error": "LLM not configured"}
        answer = _async_run(container.llm.complete(messages, model=model))
        return {"ok": True, "answer": answer}
    except Exception as exc: return {"ok": False, "error": str(exc)}

def handle_task_steps(container, task_id: str) -> dict:
    from swarm.memory.repository import MemoryRepository
    try:
        mp = container.agent.memory_port
        if mp is None: return {"ok": False, "error": "no memory port"}
        repo = MemoryRepository(mp)
        rows = _async_run(repo.query(table="task_steps", where=f"data.task_id == '{task_id}'", limit=100))
        steps = []
        for r in rows:
            steps.append(r.data)
        steps.sort(key=lambda s: s.get('step', 0))
        return {"ok": True, "task_id": task_id, "steps": steps}
    except Exception as e: return {"ok": False, "error": str(e)}

def patch_control_plane_handler(handler_class, container):
    import urllib.parse
    from swarm.memory.repository import MemoryRepository
    original_get = handler_class.do_GET
    original_post = handler_class.do_POST

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        params = dict(urllib.parse.parse_qsl(self.path.split("?", 1)[1])) if "?" in self.path else {}
        _own_get = {"/api/v1/node/info", "/api/v1/peer_list", "/api/v1/memory/records", "/api/v1/memory/ask",
                    "/api/v1/memory/knowledge_graph", "/api/v1/memory/knowledge_search", "/api/v1/memory/knowledge_note",
                    "/api/v1/memory/vector_stats", "/api/v1/agent/task_steps", "/api/v1/llm/usage"}
        if path in _own_get:
            if not self._check_auth():
                return
        _no_container = _own_get - {"/api/v1/node/info", "/api/v1/llm/usage"}
        if container is None and path in _no_container:
            self._send_json(503, {"error": "no container attached"})
            return
        if path == "/api/v1/node/info": self._send_json(200, node_info_extended(container)); return
        if path == "/api/v1/peer_list": self._send_json(200, handle_peer_list(container)); return
        if path == "/api/v1/memory/records": self._send_json(200, handle_memory_records(container, params.get("search", ""), int(params.get("limit", 30)))); return
        if path == "/api/v1/memory/ask": self._send_json(200, handle_memory_ask(container, params.get("q", ""))); return
        if path == "/api/v1/memory/knowledge_graph": self._send_json(200, handle_knowledge_graph(container)); return
        if path == "/api/v1/memory/knowledge_search":
            self._send_json(200, handle_knowledge_search(container, params.get("q", "")))
            return

        if path == "/api/v1/memory/knowledge_note": self._send_json(200, handle_knowledge_note(container, params.get("slug", ""))); return
        if path == "/api/v1/memory/vector_stats": self._send_json(200, handle_vector_stats(container)); return
        if path == "/api/v1/agent/task_steps": self._send_json(200, handle_task_steps(container, params.get("task_id", ""))); return
        if path == "/api/v1/llm/usage":
            if container is not None and container.llm is not None:
                self._send_json(200, container.llm.usage_snapshot())
            else:
                self._send_json(200, {"total_calls": 0, "calls_per_model": {}})
            return
        original_get(self)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        _own_post = {"/api/v1/memory/insert", "/api/v1/system/run_script", "/api/v1/llm/complete",
                     "/api/v1/tasks", "/api/v1/memory/insert_raw"}
        if path in _own_post:
            if not self._check_auth():
                return
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        try:
            body = json.loads(body_bytes) if body_bytes else {}
        except Exception:
            if path in _own_post:
                self._send_json(400, {"error": "invalid JSON body"})
                return
            body = {}
        if container is None and path in _own_post:
            self._send_json(503, {"error": "no container attached"})
            return
            
        if path == "/api/v1/memory/insert": self._send_json(200, handle_memory_insert(container, body)); return
        if path == "/api/v1/system/run_script": self._send_json(200, handle_run_script(container, body)); return
        if path == "/api/v1/llm/complete": self._send_json(200, handle_llm_complete(container, body)); return
        
        if path == "/api/v1/tasks":
            description = body.get("description", "").strip()
            if not description: self._send_json(400, {"error": "description is required"}); return
            try:
                import psycopg2, os
                DSN = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@127.0.0.1:5432/app_db')
                conn = psycopg2.connect(DSN); cur = conn.cursor()
                task_id = str(uuid.uuid4())
                cur.execute("INSERT INTO tasks (task_id, title, description, status, priority, created_by_node_id, created_at) VALUES (%s, %s, %s, 'pending', 'normal', 'api', NOW()) RETURNING id", (task_id, description[:80], description))
                db_id = cur.fetchone()[0]; conn.commit(); cur.close(); conn.close()
                self._send_json(201, {"id": db_id, "task_id": task_id, "status": "pending"})
                return
            except Exception as e: self._send_json(500, {"error": str(e)})
            return

        if path == "/api/v1/memory/insert_raw":
            try:
                repo = MemoryRepository(container.agent.memory_port)
                ref = _async_run(repo.save(body.get("data"), table=body.get("table"), tags=body.get("tags", []), store=body.get("store")))
                self._send_json(201, {"ref": ref, "table": body.get("table")})
            except Exception as e: self._send_json(500, {"error": str(e)})
            return
            
        self.rfile = _RebufferedRfile(body_bytes)
        original_post(self)

    handler_class.do_GET = do_GET
    handler_class.do_POST = do_POST

def handle_memory_insert(container, body: dict) -> dict:
    content = body.get("content", "").strip()
    if not content: return {"ok": False, "error": "content required"}
    try:
        mp = container.agent.memory_port; from swarm.memory.types import Artifact
        ref = _async_run(mp.put(Artifact(content=content, mime="text/plain", tags=body.get("tags", []), attrs={"title": body.get("title", "")})))
        return {"ok": True, "ref": ref}
    except Exception as e: return {"ok": False, "error": str(e)}

def handle_run_script(container, body: dict) -> dict:
    script = body.get("script", "")
    import subprocess, shlex, os
    import base64
    
    if script.startswith("octopus-agent-loop"):
        args = shlex.split(script)
        goal = args[1] if len(args) > 1 else ""
        iters = 3
        if "--iters" in args:
            iters = int(args[args.index("--iters")+1])
            
        with open("/tmp/agent_loop.py", "wb") as sf:
            sf.write(base64.b64decode(b"IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwppbXBvcnQgYXJncGFyc2UsIGpzb24sIG9zLCB0aW1lLCBzeXMsIHVybGxpYi5yZXF1ZXN0LCB1cmxsaWIucGFyc2UsIHVybGxpYi5lcnJvcgpmcm9tIGJhc2U2NCBpbXBvcnQgYjY0ZW5jb2RlCgpEQVNIX1BBU1MgPSBvcy5lbnZpcm9uLmdldCgiT0NUT1BVU19EQVNIX1BBU1MiLCAiIikKQVBJX1VSTCA9ICJodHRwOi8vMTI3LjAuMC4xOjkxMDAvYXBpL3YxIgpPTExBTUFfVVJMID0gImh0dHA6Ly8xMjcuMC4wLjE6MTE0MzQvYXBpL2dlbmVyYXRlIgpNT0RFTCA9ICJxd2VuMi41OjAuNWIiCmlmIG5vdCBEQVNIX1BBU1M6CiAgICBwcmludCgiT0NUT1BVU19EQVNIX1BBU1Mgbm90IHNldCAtIGFnZW50IGxvb3AgZGlzYWJsZWQiLCBmaWxlPXN5cy5zdGRlcnIpCiAgICBzeXMuZXhpdCgyKQoKCmRlZiBwcmludF9zdGVwKG1zZyk6CiAgICBwcmludChmIlxuW0FnZW50IExvb3BdIHttc2d9IikKCmRlZiBwcmludF9yZXN1bHQobXNnKToKICAgIHByaW50KGYiXG5bUmVzdWx0XSB7bXNnfSIpCgpkZWYgYXBpX2NhbGwocGF0aCwgbWV0aG9kPSdHRVQnLCBkYXRhPU5vbmUpOgogICAgY3JlZHMgPSBiNjRlbmNvZGUoZiJhZG1pbjp7REFTSF9QQVNTfSIuZW5jb2RlKCkpLmRlY29kZSgpCiAgICBib2R5ID0ganNvbi5kdW1wcyhkYXRhKS5lbmNvZGUoKSBpZiBkYXRhIGVsc2UgTm9uZQogICAgcmVxID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdChmIntBUElfVVJMfXtwYXRofSIsIGRhdGE9Ym9keSwgaGVhZGVycz17CiAgICAgICAgIkF1dGhvcml6YXRpb24iOiBmIkJhc2ljIHtjcmVkc30iLAogICAgICAgICJDb250ZW50LVR5cGUiOiAiYXBwbGljYXRpb24vanNvbiIKICAgIH0sIG1ldGhvZD1tZXRob2QpCiAgICB0cnk6CiAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRzKGYucmVhZCgpKQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIHJldHVybiB7Im9rIjogRmFsc2UsICJlcnJvciI6IHN0cihlKX0KCmRlZiBsbG1fYXNrX2xvY2FsKHByb21wdCk6CiAgICB0cnk6CiAgICAgICAgYm9keSA9IGpzb24uZHVtcHMoeydtb2RlbCc6IE1PREVMLCAncHJvbXB0JzogcHJvbXB0LCAnc3RyZWFtJzogRmFsc2V9KS5lbmNvZGUoKQogICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoT0xMQU1BX1VSTCwgZGF0YT1ib2R5LCBoZWFkZXJzPXsnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nfSkKICAgICAgICB3aXRoIHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTYwKSBhcyByOgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcyhyLnJlYWQoKSkuZ2V0KCdyZXNwb25zZScsICcnKS5zdHJpcCgpCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgcmV0dXJuIGYiTExNIExPQ0FMIEVSUk9SOiB7ZX0iCgpkZWYgcmVmbGVjdF9hbmRfcGxhbihnb2FsLCBwcmV2aW91c19yZXN1bHRzPU5vbmUpOgogICAgcHJpbnRfc3RlcChmIlJlZmxlY3Rpbmcgb24gR29hbDogJ3tnb2FsfSciKQogICAgY29udGV4dCA9ICIiCiAgICBpZiBwcmV2aW91c19yZXN1bHRzOgogICAgICAgIGNvbnRleHQgPSBmIlByZXZpb3VzIGV4ZWN1dGlvbiByZXN1bHRzOlxue3ByZXZpb3VzX3Jlc3VsdHN9XG5cbiIKICAgIAogICAgcHJvbXB0ID0gZiIiIllvdSBhcmUgdGhlIE1hc3RlciBBZ2VudCBPcmNoZXN0cmF0b3IuCllvdXIgb3ZlcmFyY2hpbmcgZ29hbCBpczoge2dvYWx9Cgp7Y29udGV4dH0KQW5hbHl6ZSB0aGUgY3VycmVudCBzaXR1YXRpb24gYW5kIHByb3Bvc2UgdGhlIE5FWFQgSU1NRURJQVRFIHN0ZXAgYXMgYSBzaW5nbGUgYWN0aW9uIGRlc2NyaXB0aW9uLgpSZXBseSBPTkxZIHdpdGggYSBKU09OIG9iamVjdCBpbiB0aGlzIGZvcm1hdDoKe3sKICAidGl0bGUiOiAiU2hvcnQgdGl0bGUgb2YgdGhlIHRhc2siLAogICJkZXNjcmlwdGlvbiI6ICJQTEFOIEFORCBJTVBMRU1FTlQgSU1QUk9WRU1FTlQ6IERldGFpbGVkIGRlc2NyaXB0aW9uIG9mIHdoYXQgdG8gZG8uIFVzZSB0b29scyBsaWtlIGJhc2g6IGFuZCByZWFkOiBpZiBuZWVkZWQuIiwKICAiaXNfY29tcGxldGUiOiBmYWxzZQp9fQpJZiB0aGUgb3ZlcmFyY2hpbmcgZ29hbCBpcyBmdWxseSBhY2hpZXZlZCBiYXNlZCBvbiBwcmV2aW91cyByZXN1bHRzLCBzZXQgImlzX2NvbXBsZXRlIjogdHJ1ZS4KIiIiCiAgICByZXMgPSBsbG1fYXNrX2xvY2FsKHByb21wdCkKICAgIHRyeToKICAgICAgICBjbGVhbiA9IHJlcy5zdHJpcCgpCiAgICAgICAgaWYgY2xlYW4uc3RhcnRzd2l0aCgiYGBganNvbiIpOiBjbGVhbiA9IGNsZWFuWzc6XQogICAgICAgIGlmIGNsZWFuLmVuZHN3aXRoKCJgYGAiKTogY2xlYW4gPSBjbGVhbls6LTNdCiAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoY2xlYW4uc3RyaXAoKSkKICAgIGV4Y2VwdDoKICAgICAgICByZXR1cm4geyJ0aXRsZSI6ICJQYXJzZSBFcnJvciIsICJkZXNjcmlwdGlvbiI6IGYiUExBTiBBTkQgSU1QTEVNRU5UIElNUFJPVkVNRU5UOiBGaXggcGxhbm5pbmcgbG9naWMuIFJhdzoge3Jlc30iLCAiaXNfY29tcGxldGUiOiBGYWxzZX0KCmRlZiBydW5fbG9vcChnb2FsLCBtYXhfaXRlcmF0aW9ucz01KToKICAgIHByZXZpb3VzX3Jlc3VsdHMgPSAiIgogICAgZm9yIGkgaW4gcmFuZ2UobWF4X2l0ZXJhdGlvbnMpOgogICAgICAgIHByaW50X3N0ZXAoZiItLS0gSXRlcmF0aW9uIHtpKzF9L3ttYXhfaXRlcmF0aW9uc30gLS0tIikKICAgICAgICBwbGFuID0gcmVmbGVjdF9hbmRfcGxhbihnb2FsLCBwcmV2aW91c19yZXN1bHRzKQogICAgICAgIAogICAgICAgIGlmIHBsYW4uZ2V0KCJpc19jb21wbGV0ZSIpOgogICAgICAgICAgICBwcmludF9yZXN1bHQoIkdvYWwgYWNoaWV2ZWQgc3VjY2Vzc2Z1bGx5IGFjY29yZGluZyB0byByZWZsZWN0aW9uISIpCiAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIAogICAgICAgIHRpdGxlID0gcGxhbi5nZXQoInRpdGxlIiwgZiJBdXRvLVRhc2sge2krMX0iKQogICAgICAgIGRlc2MgPSBwbGFuLmdldCgiZGVzY3JpcHRpb24iLCAiUExBTiBBTkQgSU1QTEVNRU5UIElNUFJPVkVNRU5UOiBQcm9jZWVkLiIpCiAgICAgICAgCiAgICAgICAgcHJpbnRfc3RlcChmIlBsYW5uZWQgVGFzazoge3RpdGxlfSIpCiAgICAgICAgcHJpbnQoZiJEZXNjcmlwdGlvbjoge2Rlc2N9IikKICAgICAgICAKICAgICAgICB0YXNrX3Jlc3AgPSBhcGlfY2FsbCgiL3Rhc2tzIiwgbWV0aG9kPSJQT1NUIiwgZGF0YT17InRpdGxlIjogdGl0bGUsICJkZXNjcmlwdGlvbiI6IGRlc2MsICJjcmVhdGVkQnlOb2RlSWQiOiAiYWdlbnQtbG9vcCJ9KQogICAgICAgIHRhc2tfaWQgPSB0YXNrX3Jlc3AuZ2V0KCJ0YXNrX2lkIiwgdGFza19yZXNwLmdldCgiaWQiKSkKICAgICAgICBpZiBub3QgdGFza19pZDoKICAgICAgICAgICAgcHJpbnRfcmVzdWx0KGYiRmFpbGVkIHRvIGNyZWF0ZSB0YXNrOiB7dGFza19yZXNwfSIpCiAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIAogICAgICAgIHByaW50X3N0ZXAoZiJUYXNrIGNyZWF0ZWQgd2l0aCBJRCB7dGFza19pZH0uIFdhaXRpbmcgZm9yIGNvbXBsZXRpb24uLi4iKQogICAgICAgIAogICAgICAgIGNvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgcmVzdWx0ID0gIlRpbWVvdXQiCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoNjApOgogICAgICAgICAgICB0aW1lLnNsZWVwKDEwKQogICAgICAgICAgICBzdGF0dXNfcmVzcCA9IGFwaV9jYWxsKCIvdGFza3MiKQogICAgICAgICAgICB0YXNrcyA9IHN0YXR1c19yZXNwLmdldCgidGFza3MiLCBbXSkgaWYgaXNpbnN0YW5jZShzdGF0dXNfcmVzcCwgZGljdCkgZWxzZSBzdGF0dXNfcmVzcAogICAgICAgICAgICB0ID0gbmV4dCgodCBmb3IgdCBpbiB0YXNrcyBpZiB0LmdldCgidGFza0lkIikgPT0gdGFza19pZCBvciB0LmdldCgiaWQiKSA9PSB0YXNrX2lkKSwgTm9uZSkKICAgICAgICAgICAgaWYgdDoKICAgICAgICAgICAgICAgIGlmIHQuZ2V0KCJzdGF0dXMiKSBpbiBbImNvbXBsZXRlZCIsICJmYWlsZWQiLCAiY2FuY2VsbGVkIl06CiAgICAgICAgICAgICAgICAgICAgY29tcGxldGVkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHJlc3VsdCA9IHQuZ2V0KCJyZXN1bHQiKSBvciB0LmdldCgiZXJyb3JNZXNzYWdlIikgb3IgIk5vIHJlc3VsdCBvdXRwdXQuIgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgCiAgICAgICAgcHJpbnRfcmVzdWx0KGYiVGFzayBmaW5pc2hlZC4gUmVzdWx0OiB7cmVzdWx0fSIpCiAgICAgICAgcHJldmlvdXNfcmVzdWx0cyArPSBmIlxuVGFzayB7aSsxfSAoe3RpdGxlfSkgUmVzdWx0OiB7cmVzdWx0fVxuIgogICAgCiAgICBwcmludF9zdGVwKCJBZ2VudCBsb29wIGZpbmlzaGVkLiIpCgppbXBvcnQgc3lzCnJ1bl9sb29wKHN5cy5hcmd2WzFdLCBpbnQoc3lzLmFyZ3ZbMl0pKQo="))
            
        try:
            cmd = f"python3 /tmp/agent_loop.py {shlex.quote(goal)} {iters}"
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT, timeout=600)
            return {"ok": True, "output": out}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": f"Exit {e.returncode}: {e.output}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    scripts = {"wiki_archivist": "/usr/bin/python3 /opt/octopus-wiki-archivist.py", "vector_sync": "/usr/bin/python3 /opt/octopus-obsidian-vector-sync.py", "system_doc": "/usr/bin/python3 /opt/octopus-system-doc.py", "dev_agent": "/usr/bin/python3 /opt/octopus-dev-agent.py"}
    if script not in scripts: return {"ok": False, "error": "Unknown script"}
    
    try:
        out = subprocess.check_output(scripts[script], shell=True, text=True, stderr=subprocess.STDOUT, timeout=600)
        return {"ok": True, "output": out}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"Exit {e.returncode}: {e.output}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


    return {"ok": True, "message": f"Started {script}"}

def handle_vector_stats(container) -> dict:
    v = container.vfs._vectors
    return {"count": len(v), "embedder": str(v.embedder), "sample_ids": list(v._records.keys())[:10]}

def handle_knowledge_search(container, query: str) -> dict:
    """Семантический поиск по Базе Знаний."""
    if not query: return {"ok": False, "error": "empty query"}
    try:
        # 1. Search in vector store
        v = container.vfs._vectors
        matches = v.search(query, top_k=10)
        
        results = []
        for m in matches:
            results.append({
                "ref": m.record.id,
                "text": m.record.text[:1000],
                "score": m.score,
                "metadata": m.record.metadata
            })
            
        return {"ok": True, "results": results}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
