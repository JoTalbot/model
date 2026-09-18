"""Octopus dashboards (Wave 5, item 20 — ported from AIOS).

Runnable: SafetyDashboard (stdlib), operator_dashboard_api (fastapi),
dashboard_websocket_test (manual client), seed_dashboard_data (support).
Everything else (dashboard.py, dashboard_v2/v3, run_dashboard*, views/)
is REFERENCE ONLY — see WAVE5_TRIAGE.md.
"""

from .ai_safety_dashboard import SafetyDashboard

__all__ = ["SafetyDashboard"]
