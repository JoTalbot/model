"""Unified control-plane HTTP server for the Immortal Swarm.

Replaces the minimal ``swarm.memory.dashboard`` with a multi-page SPA
and a JSON API that covers **all** subsystems: node, network, memory,
LLM, tasks, gossip and events.

Still stdlib-only — no aiohttp, no Flask — so it drops onto any device
the swarm runs on.  The SPA is a single inlined HTML string with
embedded CSS and vanilla JS; no build step, no CDN.

Endpoints
~~~~~~~~~

Static pages:
    ``/``                   Dashboard overview
    ``/nodes``              Peer list
    ``/tasks``              Task queue
    ``/memory``             Memory records + adapter metrics
    ``/network``            Topology visualisation
    ``/llm``                LLM usage
    ``/events``             Live event stream
    ``/config``             Read-only config view

JSON API:
    ``/api/v1/node/info``           Node status snapshot
    ``/api/v1/network/peers``       Kademlia peers
    ``/api/v1/network/gossip``      Recent gossip messages
    ``/api/v1/tasks``               Task list
    ``/api/v1/memory/metrics``      Per-scheme metrics
    ``/api/v1/memory/records``      Records from repository
    ``/api/v1/events/stream``       SSE event stream
    ``/api/v1/config``              Masked config
    ``/metrics``                    Prometheus exposition
    ``/healthz``                    Health probe

Control API (POST):
    ``/api/v1/tasks``               Create task
    ``/api/v1/memory/insert``       Insert record
    ``/api/v1/network/bootstrap``   Bootstrap peer

"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from swarm.api.auth import DashboardAuth, RateLimiter
from swarm.api.hardening import HardenedAuth, cors_allow_origin
from swarm.memory.port import MemoryMetrics
from swarm.memory.prom import render_metrics

_LOG = logging.getLogger("swarm.api.control_plane")


# ---------------------------------------------------------------------------
# HTML SPA (inlined — no external deps)
# ---------------------------------------------------------------------------

def _spa_html() -> str:
    from swarm.api.spa import build_spa
    return build_spa()


# ---------------------------------------------------------------------------
# PWA manifest
# ---------------------------------------------------------------------------

_MANIFEST = json.dumps({
    "name": "Immortal Swarm Control Plane",
    "short_name": "Swarm",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0e0e10",
    "theme_color": "#7dd3fc",
    "description": "Distributed P2P AI agent swarm control panel",
})


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class _ControlPlaneHandler(BaseHTTPRequestHandler):
    # These are set per-instance via subclassing (see ControlPlaneServer.start).
    _metrics: MemoryMetrics
    _audit_provider_box: list[Callable[[], dict | None] | None] = [None]
    _container: Any = None
    _collector: Any = None  # ObservabilityCollector
    _auth: DashboardAuth | None = None
    _rate_limiter: RateLimiter | None = None
    _sse_bridge: Any = None  # SSEBridge
    _hardened: HardenedAuth | None = None  # Wave 2: role-aware auth (opt-in)
    _cors_origins: list[str] = ["*"]  # Wave 2: CORS allowlist (["*"] = legacy)

    def log_message(self, fmt: str, *args: Any) -> None:
        _LOG.debug("%s - %s", self.address_string(), fmt % args)

    # ---- auth ----
    def _check_auth(self, minimum_role: str = "viewer") -> bool:
        if self._hardened is not None:
            ctx, reason = self._hardened.authorize(
                self.headers.get("Authorization", ""),
                self.client_address[0],
                minimum_role=minimum_role,
            )
            if ctx is not None:
                return True
            code = 403 if reason == "forbidden" else 401
            self._send_json(code, {"error": reason})
            return False
        if self._auth is None or not self._auth.enabled:
            return True
        auth_h = self.headers.get("Authorization", "")
        if self._auth.check_header(auth_h):
            return True
        self._send_json(401, {"error": "unauthorized"})
        return False

    def _cors_origin(self) -> str | None:
        return cors_allow_origin(self.headers.get("Origin"), self._cors_origins)

    def _check_rate(self) -> bool:
        if self._rate_limiter is None:
            return True
        ip = self.client_address[0]
        if self._rate_limiter.allow(ip):
            return True
        self._send_json(429, {"error": "rate limit exceeded"})
        return False

    # ---- send helpers ----
    def _send_text(self, code: int, body: str, ctype: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        _cors = self._cors_origin()
        if _cors is not None:
            self.send_header("Access-Control-Allow-Origin", _cors)
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Client disconnected

    def _send_json(self, code: int, payload: Any) -> None:
        self._send_text(
            code,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "application/json",
        )

    # ---- routing ----
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if not self._check_rate():
            return

        # --- Static pages (SPA) ---
        if path in ("/", "/nodes", "/tasks", "/memory", "/network",
                     "/llm", "/events", "/config", "/index.html"):
            self._send_text(200, _spa_html(), "text/html")
            return

        if path == "/manifest.json":
            self._send_text(200, _MANIFEST, "application/json")
            return

        # --- Public endpoints (no auth) ---
        if path == "/healthz":
            self._send_json(200, {
                "ok": True,
                "scheme_count": len(self._metrics.schemes()),
            })
            return

        if path == "/metrics":
            audit_stats = self._audit_stats()
            self._send_text(
                200,
                render_metrics(self._metrics, audit_stats=audit_stats),
                "text/plain",
            )
            return

        # --- Protected API ---
        if not self._check_auth():
            return

        if path == "/api/v1/node/info":
            self._handle_node_info()
            return

        if path == "/api/v1/network/peers":
            self._handle_peers()
            return

        if path == "/api/v1/memory/metrics":
            self._send_json(200, self._metrics.snapshot())
            return

        if path == "/api/v1/memory/records":
            self._handle_memory_records()
            return

        if path == "/api/v1/tasks":
            self._handle_tasks()
            return

        if path == "/api/v1/config":
            self._handle_config()
            return

        if path == "/api/v1/events/stream":
            self._handle_sse()
            return

        if path == "/api/v1/llm/usage":
            self._handle_llm_usage()
            return

        if path == "/api/v1/network/gossip":
            self._handle_gossip()
            return

        # Legacy compat
        if path == "/api/metrics":
            self._send_json(200, self._metrics.snapshot())
            return

        if path == "/api/audit":
            self._send_json(200, self._audit_stats() or {})
            return

        self._send_json(404, {"error": "not found: " + path})

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        _cors = self._cors_origin()
        if _cors is not None:
            self.send_header("Access-Control-Allow-Origin", _cors)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if not self._check_rate():
            return
        if not self._check_auth(minimum_role="operator"):
            return

        # Read body
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        try:
            body = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        if path == "/api/v1/tasks":
            self._handle_create_task(body)
            return

        if path == "/api/v1/tasks/cancel":
            self._handle_cancel_task(body)
            return

        if path == "/api/v1/memory/insert":
            self._handle_memory_insert(body)
            return

        if path == "/api/v1/network/bootstrap":
            self._handle_bootstrap_peer(body)
            return

        if path == "/api/v1/config/reload":
            self._handle_config_reload(body)
            return

        if path == "/api/v1/memory/repair/trigger":
            self._handle_trigger_repair()
            return

        if path == "/api/v1/gossip/inject":
            self._handle_gossip_inject(body)
            return

        self._send_json(404, {"error": "not found: " + path})

    # ---- POST handlers ----

    def _handle_create_task(self, body: dict) -> None:
        if self._container is None:
            self._send_json(503, {"error": "no container attached"})
            return
        description = body.get("description", "").strip()
        if not description:
            self._send_json(400, {"error": "description is required"})
            return
        from swarm.agent.core import Task
        try:
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            task = Task(
                description=description,
                creator_id=self._container.kad.node_id or "api",
            )
            loop.run_until_complete(self._container.agent.submit_task(task))
            loop.close()
            self._send_json(201, {
                "task_id": task.id,
                "status": task.status.value,
                "description": task.description,
            })
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_cancel_task(self, body: dict) -> None:
        task_id = body.get("task_id", "").strip()
        if not task_id:
            self._send_json(400, {"error": "task_id is required"})
            return
        # Attempt to find and cancel the task in the queue
        if self._container is None:
            self._send_json(503, {"error": "no container attached"})
            return
        from swarm.agent.core import TaskStatus
        q = self._container.agent.task_queue
        found = False
        if hasattr(q, '_queue'):
            for t in list(q._queue):
                if getattr(t, 'id', None) == task_id:
                    t.status = TaskStatus.FAILED
                    found = True
                    break
        self._send_json(200, {"ok": found, "task_id": task_id})

    def _handle_memory_insert(self, body: dict) -> None:
        if self._container is None:
            self._send_json(503, {"error": "no container attached"})
            return
        table = body.get("table", "").strip()
        data = body.get("data")
        if not table or data is None:
            self._send_json(400, {"error": "table and data are required"})
            return
        store = body.get("store")
        tags = body.get("tags", [])
        from swarm.memory.repository import MemoryRepository
        try:
            mp = self._container.agent.memory_port
            if mp is None:
                self._send_json(503, {"error": "memory port not configured"})
                return
            repo = MemoryRepository(mp)
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            ref = loop.run_until_complete(
                repo.save(data, table=table, tags=tags, store=store)
            )
            loop.close()
            self._send_json(201, {"ref": ref, "table": table})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_bootstrap_peer(self, body: dict) -> None:
        if self._container is None:
            self._send_json(503, {"error": "no container attached"})
            return
        host = body.get("host", "").strip()
        port = body.get("port")
        if not host or not isinstance(port, int):
            self._send_json(400, {"error": "host (str) and port (int) are required"})
            return
        try:
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            loop.run_until_complete(self._container.kad.bootstrap_peers([(host, port)]))
            loop.close()
            self._send_json(200, {"ok": True, "bootstrapped": f"{host}:{port}"})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_config_reload(self, body: dict) -> None:
        if self._container is None:
            self._send_json(503, {"error": "no container attached"})
            return
        try:
            from swarm.bootstrap.config import load_config
            from swarm.events.events import ConfigReloaded

            new_cfg = load_config("config.yaml")
            changed: list[str] = []

            # Hot-reload gossip params
            g = new_cfg.get("gossip", {})
            if isinstance(g, dict):
                iv = g.get("interval")
                if iv is not None and iv != self._container.gossip.interval:
                    self._container.gossip.interval = float(iv)
                    changed.append("gossip.interval")
                fo = g.get("fanout")
                if fo is not None and fo != self._container.gossip.fanout:
                    self._container.gossip.fanout = int(fo)
                    changed.append("gossip.fanout")

            # Hot-reload LLM models
            llm_cfg = new_cfg.get("llm", {})
            if isinstance(llm_cfg, dict) and self._container.llm is not None:
                new_models = llm_cfg.get("models") or []
                if new_models and new_models != self._container.llm.models:
                    self._container.llm.models = list(new_models)
                    changed.append("llm.models")

            if changed:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    self._container.bus.publish(ConfigReloaded(tuple(changed)))
                )
                loop.close()

            self._send_json(200, {"ok": True, "changed": changed})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_trigger_repair(self) -> None:
        if self._container is None:
            self._send_json(503, {"error": "no container attached"})
            return
        try:
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            n = loop.run_until_complete(self._container.memory.scan_and_repair_round())
            loop.close()
            self._send_json(200, {"ok": True, "blocks_checked": n or 0})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_gossip_inject(self, body: dict) -> None:
        if self._container is None:
            self._send_json(503, {"error": "no container attached"})
            return
        msg_type = body.get("msg_type", "").strip()
        payload = body.get("payload", {})
        if not msg_type:
            self._send_json(400, {"error": "msg_type is required"})
            return
        from swarm.network.gossip import GossipMessage
        try:
            msg = GossipMessage(msg_type=msg_type, payload=payload)
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            loop.run_until_complete(self._container.gossip.inject(msg))
            loop.close()
            self._send_json(200, {"ok": True, "msg_id": msg.id})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    # ---- API handlers ----

    def _handle_node_info(self) -> None:
        if self._collector is not None:
            import asyncio
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                status = loop.run_until_complete(self._collector.status())
                loop.close()
                self._send_json(200, status.to_dict())
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
        elif self._container is not None:
            # Fallback: minimal info
            info = {
                "node_id": getattr(self._container.kad, "node_id", None),
                "port": getattr(self._container, "port", None),
                "uptime_seconds": 0,
                "peers_count": 0,
                "tasks_pending": 0,
                "tasks_completed": 0,
                "tasks_failed": 0,
                "memory_schemes_active": len(self._metrics.schemes()),
                "gossip_messages_seen": 0,
                "llm_calls_total": 0,
                "blocks_stored": 0,
                "blocks_retrieved": 0,
                "nodes_known": 0,
            }
            self._send_json(200, info)
        else:
            # Standalone mode (no container)
            self._send_json(200, {
                "node_id": "standalone",
                "port": 0,
                "uptime_seconds": 0,
                "peers_count": 0,
                "peers": [],
                "tasks_pending": 0,
                "tasks_completed": 0,
                "tasks_failed": 0,
                "memory_schemes_active": len(self._metrics.schemes()),
                "gossip_messages_seen": 0,
                "llm_calls_total": 0,
                "blocks_stored": 0,
                "blocks_retrieved": 0,
                "nodes_known": 0,
            })

    def _handle_peers(self) -> None:
        if self._container is not None:
            import asyncio
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                peers = loop.run_until_complete(self._container.kad.get_peers())
                loop.close()
                self._send_json(200, {"peers": peers})
            except Exception:
                self._send_json(200, {"peers": []})
        else:
            self._send_json(200, {"peers": []})

    def _handle_memory_records(self) -> None:
        """Return latest structured memory records from the node repository."""
        if self._container is None:
            self._send_json(200, {"records": [], "count": 0})
            return
        import asyncio
        try:
            from swarm.memory.repository import MemoryRepository
            repo = MemoryRepository(self._container.agent.memory_port)
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            rows = loop.run_until_complete(repo.latest(n=50))
            loop.close()
            payload = [
                {
                    "ref": r.ref,
                    "table": r.table,
                    "data": r.data,
                    "tags": r.tags,
                    "attrs": r.attrs,
                }
                for r in rows
            ]
            self._send_json(200, {"records": payload, "count": len(payload)})
        except Exception as exc:
            self._send_json(500, {"error": str(exc), "records": [], "count": 0})

    def _handle_tasks(self) -> None:
        tasks: list[dict] = []
        if self._container is not None:
            agent = self._container.agent
            # Peek at the queue without consuming
            q = agent.task_queue
            items: list = list(q._queue) if hasattr(q, '_queue') else []
            for t in items:
                tasks.append({
                    "id": getattr(t, "id", "?"),
                    "description": getattr(t, "description", ""),
                    "status": getattr(t, "status", None),
                    "assigned_to": getattr(t, "assigned_to", None),
                })
        self._send_json(200, {"tasks": tasks})

    def _handle_config(self) -> None:
        if self._container is not None:
            cfg = dict(self._container.cfg)
            # Mask sensitive keys
            if "llm" in cfg and isinstance(cfg["llm"], dict):
                keys = cfg["llm"].get("keys", [])
                cfg["llm"]["keys"] = [k[:8] + "..." for k in keys if isinstance(k, str)]
            self._send_json(200, cfg)
        else:
            self._send_json(200, {"note": "no container attached"})

    def _handle_llm_usage(self) -> None:
        if self._container is not None and self._container.llm is not None:
            self._send_json(200, self._container.llm.usage_snapshot())
        else:
            self._send_json(200, {
                "total_calls": 0, "total_tokens_in": 0,
                "total_tokens_out": 0, "total_errors": 0,
                "calls_per_model": {}, "errors_per_model": {},
                "models": [], "local_models": [], "prefer_local": False,
            })

    def _handle_gossip(self) -> None:
        msgs = []
        stats = {}
        if self._container is not None:
            seen = self._container.gossip._seen
            recent_ids = list(seen.keys())[-50:]
            msgs = [{"id": mid} for mid in reversed(recent_ids)]
            stats = self._container.gossip.stats()
        self._send_json(200, {
            "messages": msgs,
            "total_seen": len(msgs),
            "stats": stats,
        })

    def _handle_sse(self) -> None:
        """Server-Sent Events stream."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        _cors = self._cors_origin()
        if _cors is not None:
            self.send_header("Access-Control-Allow-Origin", _cors)
        # Защита от любого upstream-прокси/CDN, который мог бы буферизовать поток
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        if self._sse_bridge is not None:
            q = self._sse_bridge.connect()
            try:
                import asyncio
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                while True:
                    try:
                        data = loop.run_until_complete(
                            asyncio.wait_for(q.get(), timeout=30.0)
                        )
                        line = f"data: {json.dumps(data, default=str)}\n\n"
                        try:
                            self.wfile.write(line.encode("utf-8"))
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    except TimeoutError:
                        # Send keepalive
                        try:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                self._sse_bridge.disconnect(q)
        else:
            # No SSE bridge — send a placeholder and close
            self.wfile.write(b"data: {\"type\":\"info\",\"payload\":{\"msg\":\"SSE bridge not configured\"}}\n\n")
            self.wfile.flush()

    @classmethod
    def _audit_stats(cls) -> dict | None:
        provider = cls._audit_provider_box[0]
        return provider() if provider else None


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class ControlPlaneServer:
    """In-process control-plane HTTP server running in a background thread.

    Drop-in replacement for :class:`MemoryDashboard` with full SPA UI
    and JSON API.

    Parameters
    ----------
    metrics:
        Live :class:`MemoryMetrics` instance.
    container:
        Optional :class:`AppContainer`.  When supplied the API can
        serve node info, peers, tasks, config, etc.
    collector:
        Optional :class:`ObservabilityCollector` for rich status.
    sse_bridge:
        Optional :class:`SSEBridge` for real-time events.
    auth:
        Optional :class:`DashboardAuth`.
    hardened:
        Optional :class:`swarm.api.hardening.HardenedAuth` (Wave 2).
        When set, it replaces the legacy auth check with role-aware,
        optionally fail-closed authorization.
    cors_origins:
        CORS allowlist (Wave 2). Default ``["*"]`` = legacy behaviour.
    """

    def __init__(
        self,
        metrics: MemoryMetrics,
        *,
        container: Any = None,
        collector: Any = None,
        sse_bridge: Any = None,
        audit_provider: Callable[[], dict | None] | None = None,
        auth: DashboardAuth | None = None,
        rate_limiter: RateLimiter | None = None,
        hardened: HardenedAuth | None = None,
        cors_origins: list[str] | None = None,
        host: str = "127.0.0.1",
        port: int = 9100,
    ) -> None:
        self._metrics = metrics
        self._container = container
        from swarm.api.web_endpoints import patch_control_plane_handler
        try:
            from swarm.api.control_plane import _ControlPlaneHandler
            patch_control_plane_handler(_ControlPlaneHandler, container)
        except Exception as _e:
            pass
        try:
            from swarm.api.web_endpoints_v2 import patch_control_plane_handler_v2

            from swarm.api.control_plane import _ControlPlaneHandler
            patch_control_plane_handler_v2(_ControlPlaneHandler, container)
        except Exception as _e:
            import logging; logging.getLogger('swarm.api.control_plane').warning('v2 patch failed: %s', _e)
        self._collector = collector
        self._sse_bridge = sse_bridge
        self._audit_provider = audit_provider
        self._auth = auth
        self._rate_limiter = rate_limiter
        self._hardened = hardened
        self._cors_origins = cors_origins if cors_origins else ["*"]
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self._port
        return self._server.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}"

    def start(self) -> None:
        if self._server is not None:
            return

        metrics = self._metrics
        container = self._container
        collector = self._collector
        sse_bridge = self._sse_bridge
        audit = self._audit_provider
        auth = self._auth
        rate_limiter = self._rate_limiter
        hardened = self._hardened
        cors_origins = self._cors_origins

        auth_open = (hardened is None or not hardened.enabled) and (
            auth is None or not auth.enabled
        )
        if auth_open and self._host not in ("127.0.0.1", "::1", "localhost"):
            _LOG.warning(
                "control-plane on %s runs WITHOUT authentication "
                "(see docs/aios/API_HARDENING.md to close it)",
                self._host,
            )

        class _BoundHandler(_ControlPlaneHandler):
            pass

        _BoundHandler._metrics = metrics
        _BoundHandler._container = container
        _BoundHandler._collector = collector
        _BoundHandler._sse_bridge = sse_bridge
        _BoundHandler._audit_provider_box = [audit]
        _BoundHandler._auth = auth
        _BoundHandler._rate_limiter = rate_limiter
        _BoundHandler._hardened = hardened
        _BoundHandler._cors_origins = cors_origins

        self._server = ThreadingHTTPServer((self._host, self._port), _BoundHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ControlPlane",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None


__all__ = ["ControlPlaneServer"]
