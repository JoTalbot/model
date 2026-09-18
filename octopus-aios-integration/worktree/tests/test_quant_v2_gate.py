"""Tests for Directional-v2 live-readiness gate."""

from __future__ import annotations

from scripts.aios.research.check_quant_v2_gate import evaluate_gate


def _portfolio(*, started_at, closed=200, realized=10.0, profit=24.0, loss=20.0, drawdown=2.0, unpriced=0):
    return {
        "kraken": {
            "closed_trades": closed,
            "realized_pnl_usd": realized,
            "net_profit_usd": profit,
            "net_loss_usd": loss,
        },
        "_risk_state": {
            "started_at": started_at,
            "max_drawdown_pct_seen": drawdown,
            "unpriced_positions": unpriced,
        },
    }


def test_gate_passes_only_when_all_requirements_hold():
    now = 40 * 86_400.0
    backtest = {
        "cost_model": "directional_v2",
        "walk_forward": True,
        "results": [{"ml_pct": 1.0}] * 12 + [{"ml_pct": -0.5}] * 8,
    }

    result = evaluate_gate(backtest, _portfolio(started_at=0.0), now=now)

    assert result["ready"] is True
    assert all(result["checks"].values())
    assert result["metrics"]["profit_factor"] == 1.2


def test_gate_fails_current_style_negative_backtest_and_short_paper_window():
    now = 2 * 86_400.0
    backtest = {"results": [{"ml_pct": -2.0}] * 23 + [{"ml_pct": 1.0}] * 9}

    result = evaluate_gate(
        backtest,
        _portfolio(started_at=now - 86_400, closed=10, realized=-5.0, profit=2.0, loss=7.0, drawdown=4.0),
        now=now,
    )

    assert result["ready"] is False
    assert result["checks"]["cost_model_v2"] is False
    assert result["checks"]["walk_forward"] is False
    assert result["checks"]["backtest_average_positive"] is False
    assert result["checks"]["paper_days_30"] is False
    assert result["checks"]["closed_trades_200"] is False
    assert result["checks"]["realized_pnl_positive"] is False
    assert result["checks"]["profit_factor_1_2"] is False
    assert result["checks"]["max_drawdown_3pct"] is False
