"""Stdlib-only web dashboard for the swarm memory facade.

Goal: open ``http://node:9100/`` from a phone browser, see live metrics,
audit-log stats and Prometheus-format text without installing anything
beyond what is already in the repo.

No aiohttp / Flask / FastAPI; everything is ``http.server`` +
``ThreadingHTTPServer``.  This keeps the dashboard a drop-in module for
nodes deployed on cheap VPSes / Termux phones / Raspberry Pis where
extra deps are expensive.

Endpoints
~~~~~~~~~

==========  ============================================================
``GET /``   HTML dashboard with metrics table and audit summary.
``GET /metrics``        Prometheus exposition format (text/plain).
``GET /healthz``        ``{"ok": true, "scheme_count": N}`` JSON.
``GET /api/metrics``    JSON snapshot of :class:`MemoryMetrics`.
``GET /api/audit``      JSON of :meth:`AuditLog.stats` (if wired in).
==========  ============================================================

The server runs in a background thread so the main asyncio event loop
that drives the swarm is never blocked.
"""

from __future__ import annotations

import html
import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from swarm.memory.port import MemoryMetrics
from swarm.memory.prom import render_metrics

_LOG = logging.getLogger("swarm.memory.dashboard")


def _html_page(metrics_snapshot: dict, audit_stats: dict | None) -> str:
    rows = []
    for scheme, row in sorted(metrics_snapshot.items()):
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(scheme)}</code></td>"
            f"<td>{row['puts']}</td>"
            f"<td>{row['gets_ok']}</td>"
            f"<td>{row['gets_err']}</td>"
            f"<td>{row['bytes_in']}</td>"
            f"<td>{row['bytes_out']}</td>"
            f"<td>{row['availability']:.2f}</td>"
            f"<td>{row.get('latency_put_p95_ms') or '-'}</td>"
            f"<td>{row.get('latency_get_p95_ms') or '-'}</td>"
            f"<td>{html.escape(row.get('last_error') or '')[:80]}</td>"
            "</tr>"
        )
    table_html = "\n".join(rows) or (
        '<tr><td colspan="10" class="muted">no metrics yet</td></tr>'
    )

    audit_html = ""
    if audit_stats:
        audit_html = (
            f"<h2>Audit log</h2>"
            f"<dl>"
            f"<dt>total events</dt><dd>{audit_stats.get('total', 0)}</dd>"
            f"<dt>bytes journalled</dt><dd>{audit_stats.get('bytes_total', 0)}</dd>"
            f"<dt>first event</dt><dd>{html.escape(audit_stats.get('first_ts') or '-')}</dd>"
            f"<dt>last event</dt><dd>{html.escape(audit_stats.get('last_ts') or '-')}</dd>"
            f"<dt>per op</dt><dd><code>{html.escape(json.dumps(audit_stats.get('per_op', {})))}</code></dd>"
            f"</dl>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Immortal swarm -- memory dashboard</title>
<style>
  :root {{
    --bg: #0e0e10; --fg: #e8e8ea; --muted: #6a6a72;
    --row: #18181b; --row-alt: #1f1f23; --accent: #7dd3fc;
    --good: #4ade80; --bad: #f87171;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 1.5rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: var(--bg); color: var(--fg);
  }}
  h1 {{ margin-top: 0; color: var(--accent); }}
  h2 {{ margin-top: 2rem; color: var(--accent); border-bottom: 1px solid var(--muted); }}
  .muted {{ color: var(--muted); }}
  .topbar {{ display:flex; gap:1rem; flex-wrap:wrap; align-items:center; }}
  .topbar a {{
    color: var(--accent); text-decoration: none; padding: .25rem .5rem;
    border: 1px solid var(--muted); border-radius: .25rem;
  }}
  table {{ width: 100%; border-collapse: collapse; margin-top: .75rem; }}
  th, td {{ text-align: left; padding: .35rem .6rem; }}
  thead th {{ position: sticky; top:0; background: var(--row); color: var(--accent); }}
  tbody tr:nth-child(odd)  {{ background: var(--row); }}
  tbody tr:nth-child(even) {{ background: var(--row-alt); }}
  td code {{ color: var(--good); }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1rem; }}
  dt {{ color: var(--muted); }}
</style>
</head>
<body>
<h1>Immortal swarm -- memory dashboard</h1>
<div class="topbar">
  <a href="/metrics">/metrics (Prometheus)</a>
  <a href="/api/metrics">/api/metrics (JSON)</a>
  <a href="/api/audit">/api/audit (JSON)</a>
  <a href="/healthz">/healthz</a>
</div>
<h2>Per-scheme metrics</h2>
<table>
  <thead><tr>
    <th>scheme</th>
    <th>puts</th>
    <th>gets ok</th>
    <th>gets err</th>
    <th>bytes in</th>
    <th>bytes out</th>
    <th>availability</th>
    <th>put p95 ms</th>
    <th>get p95 ms</th>
    <th>last error</th>
  </tr></thead>
  <tbody>
    {table_html}
  </tbody>
</table>
{audit_html}
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    metrics: MemoryMetrics
    # Stored in a 1-element list to dodge Python's descriptor protocol --
    # otherwise a function attached as a class attribute is auto-bound
    # to ``self`` on access.
    _audit_provider_box: list[Callable[[], dict | None] | None] = [None]

    def log_message(self, fmt: str, *args: Any) -> None:
        _LOG.debug("%s - %s", self.address_string(), fmt % args)

    @classmethod
    def _audit_stats(cls) -> dict | None:
        provider = cls._audit_provider_box[0]
        return provider() if provider else None

    def _send_text(self, code: int, body: str, ctype: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, code: int, payload: Any) -> None:
        self._send_text(
            code,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "application/json",
        )

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        audit_stats: dict | None = self._audit_stats()

        if path == "/" or path == "/index.html":
            self._send_text(
                200,
                _html_page(self.metrics.snapshot(), audit_stats),
                "text/html",
            )
            return

        if path == "/metrics":
            self._send_text(
                200,
                render_metrics(self.metrics, audit_stats=audit_stats),
                "text/plain",
            )
            return

        if path == "/api/metrics":
            self._send_json(200, self.metrics.snapshot())
            return

        if path == "/api/audit":
            self._send_json(200, audit_stats or {})
            return

        if path == "/healthz":
            self._send_json(200, {
                "ok": True,
                "scheme_count": len(self.metrics.schemes()),
            })
            return

        self._send_text(404, '{"error":"not found"}', "application/json")


class MemoryDashboard:
    """In-process HTTP dashboard that runs in a background thread.

    Parameters
    ----------
    metrics:
        Live :class:`MemoryMetrics` instance.  The dashboard only reads;
        the actual swarm continues to write to it.
    audit_provider:
        Optional zero-arg callable that returns the latest
        :meth:`AuditLog.stats` result.  We call it on every request so
        the dashboard reflects fresh data without race-prone caching.
    host, port:
        Bind address.  ``host="0.0.0.0"`` for LAN reachable, ``port=0``
        for ephemeral binding (used by tests).
    """

    def __init__(
        self,
        metrics: MemoryMetrics,
        *,
        audit_provider: Callable[[], dict | None] | None = None,
        host: str = "127.0.0.1",
        port: int = 9100,
    ) -> None:
        self._metrics = metrics
        self._audit_provider = audit_provider
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

        # Bind a per-instance handler subclass so each dashboard
        # carries its own metrics reference without leaking class state.
        metrics = self._metrics
        audit = self._audit_provider

        class _BoundHandler(_Handler):
            pass

        _BoundHandler.metrics = metrics
        _BoundHandler._audit_provider_box = [audit]

        self._server = ThreadingHTTPServer((self._host, self._port), _BoundHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="MemoryDashboard",
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


__all__ = ["MemoryDashboard"]
