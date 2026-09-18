"""Tests for the A/B trade-log bootstrap verdict."""

from __future__ import annotations

import pytest

from swarm.quant.quant_ab_report import ab_verdict, load_trade_pnls


def _portfolio_with_log(pnls):
    return {
        "binance": {"trade_log": [{"net_pnl_usd": v} for v in pnls]},
        "_risk_state": {},
    }


def test_load_trade_pnls_aggregates_and_skips_meta():
    data = {
        "binance": {"trade_log": [{"net_pnl_usd": 1.0}, {"net_pnl_usd": -2.5}]},
        "kraken": {"trade_log": [{"net_pnl_usd": 0.5}]},
        "_risk_state": {"x": 1},
        "cross_arbitrage": {"trade_log": [{"net_pnl_usd": 99.0}]},
    }
    pnls = load_trade_pnls(data)
    assert pnls == [1.0, -2.5, 0.5]


def test_load_trade_pnls_handles_missing_and_bad_values():
    assert load_trade_pnls({}) == []
    assert load_trade_pnls({"binance": {"trade_log": [{"net_pnl_usd": None},
                                                       {"net_pnl_usd": "oops"}]}}) == []


def test_ab_verdict_none_below_min_trades():
    assert ab_verdict([1.0] * 10, [0.5] * 14) is None


def test_ab_verdict_detects_clear_difference():
    pytest.importorskip("numpy")
    rng_main = [1.0, 0.8, 1.2, 0.9, 1.1] * 3
    rng_control = [-1.0, -0.8, -1.2, -0.9, -1.1] * 3
    v = ab_verdict(rng_main, rng_control, min_trades=15, n_boot=500)
    assert v is not None
    assert v["winner"] == "main"
    assert v["significant"] is True
    assert v["ci90"][0] > 0


def test_ab_verdict_no_difference_not_significant():
    pytest.importorskip("numpy")
    a = [0.2, -0.1, 0.3, -0.2, 0.0, 0.4, -0.3, 0.1] * 4
    v = ab_verdict(a, list(a), min_trades=15, n_boot=500)
    assert v is not None
    assert v["diff_obs"] == 0.0
    assert v["significant"] is False
    assert v["winner"] == "tie"
