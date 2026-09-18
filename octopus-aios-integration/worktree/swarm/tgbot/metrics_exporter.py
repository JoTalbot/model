"""Minimal Prometheus HTTP exporter embedded in the Telegram bot process."""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from swarm.tgbot.metrics import render_telegram_prometheus


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.rstrip("/") not in ("", "/metrics"):
            self.send_error(404)
            return
        payload = render_telegram_prometheus().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _create_server() -> ThreadingHTTPServer | None:
    if os.environ.get("TELEGRAM_PROMETHEUS_ENABLED", "1").lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return None
    host = os.environ.get("TELEGRAM_PROMETHEUS_HOST", "0.0.0.0")
    port = int(os.environ.get("TELEGRAM_PROMETHEUS_PORT", "9103"))
    try:
        return ThreadingHTTPServer((host, port), _MetricsHandler)
    except OSError as exc:
        print(f"⚠️ Telegram Prometheus exporter disabled: {type(exc).__name__}")
        return None


def start_metrics_exporter() -> ThreadingHTTPServer | None:
    server = _create_server()
    if server is None:
        return None
    thread = threading.Thread(
        target=server.serve_forever,
        name="telegram-prometheus-exporter",
        daemon=True,
    )
    thread.start()
    print(
        f"📈 Telegram Prometheus exporter listening on port {server.server_address[1]}"
    )
    return server


def run_metrics_exporter() -> int:
    """Run a blocking exporter process for Docker/sidecar deployments."""
    server = _create_server()
    if server is None:
        return 1
    print(
        f"📈 Telegram Prometheus exporter listening on port {server.server_address[1]}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_metrics_exporter())
