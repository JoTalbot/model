"""Tests for the A/B paper comparison logic."""

from __future__ import annotations

from swarm.quant.quant_ab_report import compare_portfolios


def _portfolio(closed: int, wins: int, realized: float, fees: float,
               net_profit: float, net_loss: float) -> dict:
    return {
        "binance": {
            "closed_trades": closed,
            "winning_trades": wins,
            "realized_pnl_usd": realized,
            "gross_pnl_usd": realized + fees,
            "fees_paid_usd": fees,
            "execution_costs_usd": 0.1,
            "net_profit_usd": net_profit,
            "net_loss_usd": net_loss,
        },
        "_risk_state": {"equity_usd": 9990.0, "max_drawdown_pct_seen": 0.1, "entry_mode": "enabled"},
    }


def test_compare_portfolios_aggregates():
    main = _portfolio(closed=3, wins=1, realized=-2.0, fees=0.6, net_profit=1.0, net_loss=3.0)
    control = _portfolio(closed=0, wins=0, realized=0.0, fees=0.0, net_profit=0.0, net_loss=0.0)
    c = compare_portfolios(main, control)

    assert c["main"]["closed_trades"] == 3
    assert c["main"]["win_rate_pct"] == 33.3
    assert c["main"]["realized_pnl_usd"] == -2.0
    assert c["main"]["profit_factor"] == 0.333
    assert c["main"]["equity_usd"] == 9990.0
    assert c["control"]["closed_trades"] == 0
    assert c["control"]["win_rate_pct"] is None
    assert c["control"]["profit_factor"] is None


def test_compare_portfolios_zero_losses_gives_no_pf():
    main = _portfolio(closed=2, wins=2, realized=5.0, fees=0.2, net_profit=5.0, net_loss=0.0)
    control = _portfolio(closed=0, wins=0, realized=0.0, fees=0.0, net_profit=0.0, net_loss=0.0)
    c = compare_portfolios(main, control)
    assert c["main"]["profit_factor"] is None
    assert c["main"]["win_rate_pct"] == 100.0
