"""Deterministic tests for offline cost-aware walk-forward backtest."""

from __future__ import annotations

from scripts.aios.research.run_quant_walkforward_v2 import Params, simulate, walk_forward


def _rows(count=500, drift=0.002):
    rows = []
    price = 100.0
    for index in range(count):
        cycle = -0.01 if index % 20 < 4 else drift
        price *= 1.0 + cycle
        rows.append({"timestamp": index * 3_600_000.0, "open": price, "high": price * 1.002, "low": price * 0.998, "close": price, "volume": 1_000.0})
    return rows


def test_simulation_accounts_for_costs_and_returns_metrics():
    result = simulate(_rows(), Params(3, 10, 35.0, 2.0, 1.0))

    assert result["closed_trades"] > 0
    assert result["fees_usd"] > 0
    assert result["execution_costs_usd"] > 0
    assert "profit_factor" in result
    assert "max_drawdown_pct" in result


def test_walk_forward_uses_disjoint_train_and_test_windows():
    result = walk_forward(_rows())

    assert result["train_rows"] == 350
    assert result["test_rows"] == 150
    assert result["train_rows"] + result["test_rows"] == result["rows"]
    assert result["params"]["fast"] < result["params"]["slow"]
    assert result["test"]["closed_trades"] >= 0
