"""Tests for swarm.memory.dashboard -- stdlib-only HTTP dashboard."""

from __future__ import annotations

import json
import urllib.request

import pytest

from swarm.memory.dashboard import MemoryDashboard
from swarm.memory.port import MemoryMetrics


@pytest.fixture
def metrics() -> MemoryMetrics:
    m = MemoryMetrics()
    m.record_put("catbox")
    m.record_put("catbox")
    m.record_get("catbox", ok=True)
    m.record_get("catbox", ok=False)
    m.record_bytes_in("catbox", 200)
    m.record_bytes_out("catbox", 100)
    m.record_latency("catbox", "put", 0.012)
    return m


@pytest.fixture
def dash(metrics: MemoryMetrics):
    d = MemoryDashboard(metrics, host="127.0.0.1", port=0)
    d.start()
    yield d
    d.stop()


def _get(url: str) -> tuple[int, dict, str]:
    with urllib.request.urlopen(url, timeout=2.0) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, dict(resp.headers), body


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_dashboard_starts_on_ephemeral_port(dash):
    assert dash.port > 0
    assert dash.url.startswith("http://127.0.0.1:")


def test_dashboard_root_returns_html(dash):
    status, headers, body = _get(dash.url + "/")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert "Immortal swarm" in body
    assert "catbox" in body


def test_dashboard_metrics_endpoint_is_prometheus_text(dash):
    status, headers, body = _get(dash.url + "/metrics")
    assert status == 200
    assert "text/plain" in headers["Content-Type"]
    assert "# HELP swarm_memory_puts_total" in body
    assert 'swarm_memory_puts_total{scheme="catbox"} 2' in body


def test_dashboard_api_metrics_returns_json(dash):
    status, headers, body = _get(dash.url + "/api/metrics")
    assert status == 200
    assert "application/json" in headers["Content-Type"]
    data = json.loads(body)
    assert "catbox" in data
    assert data["catbox"]["puts"] == 2


def test_dashboard_healthz_is_json_ok(dash):
    status, _, body = _get(dash.url + "/healthz")
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["scheme_count"] == 1


def test_dashboard_404_for_unknown_path(dash):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(dash.url + "/nope", timeout=2.0)
    assert exc.value.code == 404


def test_dashboard_api_audit_returns_empty_dict_when_no_provider(dash):
    status, _, body = _get(dash.url + "/api/audit")
    assert status == 200
    assert json.loads(body) == {}


def test_dashboard_audit_provider_is_called_per_request(metrics):
    call_count = {"n": 0}

    def provider() -> dict:
        call_count["n"] += 1
        return {
            "total": 5,
            "per_op": {"put": 3, "get": 2},
            "per_scheme_ok": {"catbox": 4},
            "per_scheme_err": {"catbox": 1},
            "bytes_total": 999,
            "first_ts": "2026-05-13T10:00:00+00:00",
            "last_ts": "2026-05-13T18:00:00+00:00",
        }

    d = MemoryDashboard(metrics, audit_provider=provider, host="127.0.0.1", port=0)
    d.start()
    try:
        _, _, root = _get(d.url + "/")
        assert "Audit log" in root
        assert "999" in root  # bytes_total in dl
        _, _, audit_body = _get(d.url + "/api/audit")
        audit = json.loads(audit_body)
        assert audit["total"] == 5
        _, _, prom = _get(d.url + "/metrics")
        assert "swarm_memory_audit_total" in prom
        assert call_count["n"] >= 3
    finally:
        d.stop()


def test_dashboard_can_be_started_and_stopped_multiple_times(metrics):
    d = MemoryDashboard(metrics, host="127.0.0.1", port=0)
    d.start()
    d.start()  # idempotent
    port = d.port
    assert port > 0
    d.stop()
    d.stop()  # idempotent
    # After stop, starting again works
    d.start()
    try:
        status, _, _ = _get(d.url + "/healthz")
        assert status == 200
    finally:
        d.stop()


def test_dashboard_handles_html_escape_on_scheme_with_special_chars():
    m = MemoryMetrics()
    m.record_put("<bad>scheme")
    d = MemoryDashboard(m, host="127.0.0.1", port=0)
    d.start()
    try:
        _, _, body = _get(d.url + "/")
        assert "<bad>scheme" not in body
        assert "&lt;bad&gt;scheme" in body
    finally:
        d.stop()
