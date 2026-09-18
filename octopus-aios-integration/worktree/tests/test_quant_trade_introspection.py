"""Tests for Directional-v2 trade introspection."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "aios"))

import run_quant_trading as runner


def test_trade_line_entry():
    line = runner.trade_line(
        {
            "exchange": "kucoin",
            "symbol": "BTC",
            "action": "BUY_LONG",
            "mid_price": 63105.2,
            "execution_price": 63136.8,
            "fees_usd": 0.63,
            "execution_cost_usd": 0.32,
            "ml_prob_up": 0.51,
            "signal_confidence": 0.9,
        }
    )
    assert "kucoin:BTC" in line
    assert "BUY_LONG" in line
    assert "conf=0.9" in line and "ml_up=0.51" in line


def test_trade_line_close():
    line = runner.trade_line(
        {
            "exchange": "binance",
            "symbol": "ETH",
            "action": "CLOSE",
            "reason": "take_profit",
            "mid_price": 1900.0,
            "net_pnl_usd": 1.5,
            "gross_pnl_usd": 2.1,
            "fees_usd": 0.6,
        }
    )
    assert "binance:ETH" in line and "CLOSE(take_profit)" in line
    assert "net=+1.5000" in line


def test_run_cycle_logs_trade_lines(caplog):
    class Multi:
        def run_multi_exchange_cycle(self):
            return {
                "cycle_trades": [
                    {
                        "exchange": "kraken",
                        "symbol": "ADA",
                        "action": "BUY_LONG",
                        "mid_price": 0.17,
                        "execution_price": 0.171,
                        "fees_usd": 0.0,
                        "execution_cost_usd": 0.0,
                        "ml_prob_up": 0.55,
                        "signal_confidence": 0.91,
                    }
                ],
                "risk": {
                    "entry_mode": "enabled",
                    "drawdown_pct": 0.0,
                    "daily_loss_pct": 0.0,
                },
            }

    import logging

    with caplog.at_level(logging.INFO, logger="Octopus.RunQuantTrading"):
        runner.run_cycle(None, Multi())
    assert any("kraken:ADA BUY_LONG" in rec.message for rec in caplog.records)
