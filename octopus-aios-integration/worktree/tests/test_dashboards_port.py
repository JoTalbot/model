"""Wave 5a: runnable dashboard ports (item 20)."""

import sqlite3

from swarm.dashboards.ai_safety_dashboard import SafetyDashboard
from swarm.dashboards.operator_dashboard_api import app
from swarm.dashboards.seed_dashboard_data import seed


def test_safety_initial_healthy():
    d = SafetyDashboard()
    assert d.safety_score == 1.0
    assert d.get_dashboard()["status"] == "healthy"


def test_safety_metric_threshold_lowers_score():
    d = SafetyDashboard()
    d.update_metric("harm", 0.9)
    assert d.safety_score < 1.0
    assert d.get_dashboard()["compliance_status"] == "non-compliant"
    audit = d.compliance_audit()
    assert audit["compliant"] is False
    assert any("harm" in v for v in audit["violations"])


def test_safety_incident_severity_normalized():
    d = SafetyDashboard()
    d.add_incident({"title": "x", "severity": "bogus"})
    assert d.incidents[-1]["severity"] == "medium"
    assert d.incident_summary()["total_incidents"] == 1


def test_safety_trend_and_correlation():
    d = SafetyDashboard()
    assert d.trend_report("harm")["trend"] == "insufficient_data"
    for v in (0.1, 0.2, 0.35):
        d.update_metric("harm", v)
        d.update_metric("bias", v * 2)
    assert d.trend_report("harm")["trend"] == "improving"
    corr = d.metric_correlation("harm", "bias")
    assert corr["correlation"] > 0.99


def test_operator_bridge_ws_route():
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/ws/thoughts" in paths
    assert app.title == "Octopus Operator Matrix API"


def test_seed_creates_schema(tmp_path):
    db = tmp_path / "dash.sqlite"
    seed(str(db))
    con = sqlite3.connect(db)
    tables = {
        r[0] for r in con.execute("select name from sqlite_master where type='table'")
    }
    assert {"tasks", "memory_items"} <= tables
    con.close()


def test_ws_client_imports():
    import swarm.dashboards.dashboard_websocket_test as m

    assert callable(m.run_test)
