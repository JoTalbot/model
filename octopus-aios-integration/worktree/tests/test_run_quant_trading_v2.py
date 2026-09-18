"""Runner contract for paper-only Directional v2."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "aios"))

import run_quant_trading as runner


def test_build_engines_disables_legacy_and_uses_v2_state(monkeypatch):
    captured = {}

    class Multi:
        def __init__(self, *, portfolio_filename):
            captured["filename"] = portfolio_filename

    monkeypatch.delenv("OCTOPUS_QUANT_LEGACY_EXECUTION", raising=False)
    monkeypatch.delenv("OCTOPUS_QUANT_PORTFOLIO_FILE", raising=False)
    monkeypatch.setattr(runner, "MultiExchangeQuantEngine", Multi)

    legacy, multi = runner.build_engines()

    assert legacy is None
    assert isinstance(multi, Multi)
    assert captured["filename"] == "multi_exchange_portfolios_v2.json"


def test_run_cycle_reports_frozen_risk_without_legacy():
    class Multi:
        def run_multi_exchange_cycle(self):
            return {
                "cycle_trades": [],
                "risk": {
                    "entry_mode": "freeze",
                    "drawdown_pct": 0.0,
                    "daily_loss_pct": 0.0,
                },
            }

    result = runner.run_cycle(None, Multi())

    assert result["legacy"] == {"signals": [], "legacy_execution": False}
    assert result["multi"]["risk"]["entry_mode"] == "freeze"
