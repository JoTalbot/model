"""Wave 5b: T2 metrics (needs numpy; skipped in prod venv)."""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from scripts.aios.freqtrade.quant_t2_metrics import portfolio_metrics, trade_metrics


def test_trade_metrics_known_sequence():
    trades = [{"equity": 10000}, {"equity": 10100}, {"equity": 10050}, {"equity": 10200}]
    m = trade_metrics(trades, final_equity=10200)
    assert m["n_trades"] == 4
    assert m["win_rate_pct"] == 50.0
    assert m["expectancy_usd"] == 50.0
    assert m["total_from_10k_pct"] == 2.0
    # PF: wins 100+150=250, losses 50 -> 5.0
    assert m["profit_factor"] == 5.0


def test_trade_metrics_no_losses_infinite_pf():
    trades = [{"equity": 10000}, {"equity": 10100}]
    m = trade_metrics(trades, final_equity=10100)
    assert m["profit_factor"] is None  # ∞ не выразимо


def test_trade_metrics_empty():
    assert trade_metrics([], 10000) is None


def test_portfolio_metrics_known_growth():
    rows = [{"portfolio": 10000 + i * 100} for i in range(40)]
    pm = portfolio_metrics(rows)
    assert pm["total_pct"] > 0
    assert pm["max_dd_pct"] == 0.0
    assert pm["sharpe"] > 0
    assert pm["n_days"] == 40


def test_portfolio_metrics_short_history():
    assert portfolio_metrics([{"portfolio": 1}] * 3) is None
