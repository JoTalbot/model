"""
swarm/api/web_endpoints_v2.py
──────────────────────────────
Регистрация v2-эндпоинтов: файлообменник + граф + процессы + рой + reflect.
"""
from __future__ import annotations

import io
import json
import logging
import urllib.parse

_LOG = logging.getLogger("swarm.api.web_endpoints_v2")


class _RebufferedRfile:
    def __init__(self, b): self._buf = io.BytesIO(b)
    def read(self, n=-1):
        return self._buf.read(n) if n is not None and n >= 0 else self._buf.read()
    def close(self): self._buf.close()
    def readable(self): return True
    def readline(self, n=-1): return self._buf.readline(n)


def patch_control_plane_handler_v2(handler_class, container):
    from swarm.api import files_endpoints as F
    from swarm.api import graph_endpoints as G
    from swarm.api import spawn_endpoints as S

    original_get  = handler_class.do_GET
    original_post = handler_class.do_POST

    def do_GET(self):
        path_full = self.path
        path = path_full.split("?", 1)[0]
        qs   = path_full.split("?", 1)[1] if "?" in path_full else ""
        params = dict(urllib.parse.parse_qsl(qs))

        # SPA-маршруты (отдаём HTML)
        if path in ("/files", "/graph", "/processes", "/swarm", "/reflect"):
            self.path = "/" + ("?" + qs if qs else "")
            return original_get(self)

        # Files
        if path == "/api/v1/files/list":
            self._send_json(200, F.handle_files_list(
                container, params.get("path", "/"),
                params.get("search", ""), params.get("tag", "")))
            return
        if path == "/api/v1/files/tree":
            self._send_json(200, F.handle_files_tree(container)); return
        if path == "/api/v1/files/stats":
            self._send_json(200, F.handle_files_stats(container)); return
        if path == "/api/v1/files/download":
            res = F.handle_files_download(container, params.get("ref", ""))
            if res is None:
                self._send_json(404, {"ok": False, "error": "not found"}); return
            mime, name, blob = res
            self.send_response(200)
            self.send_header("Content-Type", mime)
            # filename* для UTF-8 имён
            safe = urllib.parse.quote(name)
            self.send_header("Content-Disposition",
                f"attachment; filename=\"{safe}\"; filename*=UTF-8''{safe}")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(blob)
            return
        if path == "/api/v1/files/raw":
            # тоже что /download, но без attachment-заголовка (для inline preview)
            res = F.handle_files_download(container, params.get("ref", ""))
            if res is None:
                self._send_json(404, {"ok": False, "error": "not found"}); return
            mime, name, blob = res
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(blob)
            return

        # Graph / types / timeline
        if path == "/api/v1/memory/graph":
            scope = params.get("scope", "all")
            try: max_n = int(params.get("max_nodes", "250"))
            except Exception: max_n = 250
            self._send_json(200, G.handle_memory_graph(container, scope, max_n)); return
        if path == "/api/v1/memory/types":
            self._send_json(200, G.handle_memory_types(container)); return
        if path == "/api/v1/memory/timeline":
            try: days = int(params.get("days", "7"))
            except Exception: days = 7
            self._send_json(200, G.handle_memory_timeline(container, days)); return
        if path == "/api/v1/swarm/processes":
            self._send_json(200, G.handle_swarm_processes(container)); return

        # Swarm management
        if path == "/api/v1/swarm/nodes":
            self._send_json(200, S.handle_swarm_nodes(container)); return
        if path == "/api/v1/agent/reflect":
            self._send_json(200, S.handle_agent_reflect(container)); return

        # Auth-check before passing to original_get (protected API routes)
        if path.startswith("/api/"):
            if hasattr(self, "_check_auth") and not self._check_auth():
                return
        original_get(self)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes  = self.rfile.read(content_len) if content_len > 0 else b""

        # raw upload
        if path == "/api/v1/files/upload":
            headers = {k: v for k, v in self.headers.items()}
            self._send_json(200, F.handle_files_upload(container, body_bytes, headers))
            return

        try:
            body = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            body = {}

        if path == "/api/v1/files/delete":
            self._send_json(200, F.handle_files_delete(container, body)); return
        if path == "/api/v1/files/move":
            self._send_json(200, F.handle_files_move(container, body)); return
        if path == "/api/v1/files/mkdir":
            self._send_json(200, F.handle_files_mkdir(container, body)); return
        if path == "/api/v1/files/tag":
            self._send_json(200, F.handle_files_tag(container, body)); return
        if path == "/api/v1/files/migrate_payload":
            self._send_json(200, S.handle_files_migrate_payload(container, body)); return

        if path == "/api/v1/swarm/spawn":
            self._send_json(200, S.handle_swarm_spawn(container, body)); return
        if path == "/api/v1/swarm/kill":
            self._send_json(200, S.handle_swarm_kill(container, body)); return

        # делегируем оригиналу с восстановленным rfile
        self.rfile = _RebufferedRfile(body_bytes)
        self.headers["Content-Length"] = str(len(body_bytes))
        original_post(self)

    handler_class.do_GET  = do_GET
    handler_class.do_POST = do_POST
    _LOG.info("Web endpoints v2 patch applied (files + graph + processes + swarm + reflect)")
