"""Integration tests for cost-aware multi-exchange paper execution v2."""

from __future__ import annotations

import time

import pytest

from swarm.quant.quant_trading_engine import MultiExchangeQuantEngine


class FakeSignalEngine:
    def __init__(self, analysis):
        self.analysis = analysis
        self.calls = 0

    def load_history(self):
        return {}

    def save_history(self, _history):
        return None

    def record_and_analyze(self, _symbol, _price):
        self.calls += 1
        return dict(self.analysis)


def _engine(tmp_path, analysis, price=100.0):
    engine = MultiExchangeQuantEngine(data_dir=str(tmp_path))
    engine.signal_engine = FakeSignalEngine(analysis)
    engine.fetch_all_exchange_prices = lambda: {"kraken": {"BTC": price}}
    return engine


def _buy_signal(**overrides):
    return {
        "signal": "BUY_LONG",
        "confidence": 0.90,
        "ml_prob_up": 0.70,
        "rl_position": 0.60,
        **overrides,
    }


def test_default_freeze_blocks_new_entries(monkeypatch, tmp_path):
    monkeypatch.delenv("OCTOPUS_QUANT_ENTRY_MODE", raising=False)
    engine = _engine(tmp_path, _buy_signal())

    result = engine.run_multi_exchange_cycle()
    portfolio = engine.load_portfolios()["kraken"]

    assert portfolio["positions"] == {}
    assert result["risk"]["entry_mode"] == "freeze"
    assert result["risk"]["block_reasons"]["entry_mode_freeze"] == 1
    assert engine.signal_engine.calls == 0


def test_enabled_entry_models_fee_spread_slippage_and_accounting(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOPUS_QUANT_ENTRY_MODE", "enabled")
    engine = _engine(tmp_path, _buy_signal())

    result = engine.run_multi_exchange_cycle()
    portfolio = engine.load_portfolios()["kraken"]
    position = portfolio["positions"]["BTCUSD"]

    assert position["entry_mid_price"] == 100.0
    assert position["entry_price"] == pytest.approx(100.1)
    assert position["entry_fee_usd"] == pytest.approx(0.3)
    assert position["entry_execution_cost_usd"] > 0
    assert portfolio["entry_count"] == 1
    assert portfolio["closed_trades"] == 0
    assert portfolio["fees_paid_usd"] == pytest.approx(0.3)
    assert result["risk"]["round_trip_cost_pct"] == pytest.approx(0.5)

    second = engine.run_multi_exchange_cycle()
    assert second["cycle_trades"] == []
    assert second["risk"]["block_reasons"]["same_candle"] == 1
    assert engine.signal_engine.calls == 1


def test_drawdown_and_ml_veto_block_entries(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOPUS_QUANT_ENTRY_MODE", "enabled")
    engine = _engine(tmp_path, _buy_signal())
    data = engine.load_portfolios()
    data["kraken"]["cash_usd"] = 900.0
    engine.save_portfolios(data)

    drawdown = engine.run_multi_exchange_cycle()
    assert drawdown["risk"]["drawdown_pct"] == pytest.approx(1.0)
    assert drawdown["risk"]["block_reasons"]["global_drawdown_kill"] == 1

    # New state/candle fixture: no drawdown, but model has no edge.
    other = _engine(tmp_path / "ml", _buy_signal(ml_prob_up=0.52))
    ml_veto = other.run_multi_exchange_cycle()
    assert ml_veto["risk"]["block_reasons"]["ml_not_confirmed"] == 1


def test_stop_loss_records_gross_costs_and_net_pnl(monkeypatch, tmp_path):
    monkeypatch.delenv("OCTOPUS_QUANT_ENTRY_MODE", raising=False)
    engine = _engine(tmp_path, {"signal": "HOLD", "confidence": 0.5}, price=98.0)
    data = engine.load_portfolios()
    quantity = 199.7 / 100.1
    entry_execution_cost = quantity * 0.1
    data["kraken"].update(
        {
            "cash_usd": 800.0,
            "entry_count": 1,
            "total_trades": 1,
            "closed_trades": 0,
            "fees_paid_usd": 0.3,
            "execution_costs_usd": entry_execution_cost,
            "positions": {
                "BTCUSD": {
                    "side": "LONG",
                    "entry_price": 100.1,
                    "entry_mid_price": 100.0,
                    "qty": quantity,
                    "invested_usd": 200.0,
                    "entry_fee_usd": 0.3,
                    "entry_execution_cost_usd": entry_execution_cost,
                    "max_price_seen": 100.0,
                    "opened_at": time.time() - 10_000,
                }
            },
        }
    )
    engine.save_portfolios(data)

    result = engine.run_multi_exchange_cycle()
    portfolio = engine.load_portfolios()["kraken"]
    trade = result["cycle_trades"][0]

    assert trade["action"] == "CLOSE"
    assert trade["reason"] == "stop_loss"
    assert trade["gross_pnl_usd"] < 0
    assert trade["net_pnl_usd"] < trade["gross_pnl_usd"]
    assert trade["fees_usd"] > 0.3
    assert trade["execution_cost_usd"] > entry_execution_cost
    assert portfolio["positions"] == {}
    assert portfolio["closed_trades"] == 1
    assert portfolio["winning_trades"] == 0
    assert portfolio["net_profit_usd"] == 0.0
    assert portfolio["net_loss_usd"] == pytest.approx(abs(trade["net_pnl_usd"]))
    assert portfolio["realized_pnl_usd"] == pytest.approx(trade["net_pnl_usd"])


# NOTE(octopus-wave4): test_market_universe_uses_current_asset_symbols dropped —
# it covers data_collector.DEFAULT_SYMBOLS, deferred to Wave 5 (item 3).


def _open_position(
    data,
    symbol="BTCUSD",
    *,
    max_seen=100.0,
    entry_mid=100.0,
    quantity=None,
    opened_seconds_ago=10_000,
):
    """Place a LONG position in the kraken portfolio (mirrors test_stop_loss fixture)."""
    quantity = quantity or (199.7 / 100.1)
    entry_execution_cost = quantity * 0.1
    data["kraken"].update(
        {
            "cash_usd": 800.0,
            "entry_count": 1,
            "total_trades": 1,
            "closed_trades": 0,
            "fees_paid_usd": 0.3,
            "execution_costs_usd": entry_execution_cost,
            "positions": {
                symbol: {
                    "side": "LONG",
                    "entry_price": 100.1,
                    "entry_mid_price": entry_mid,
                    "qty": quantity,
                    "invested_usd": 200.0,
                    "entry_fee_usd": 0.3,
                    "entry_execution_cost_usd": entry_execution_cost,
                    "max_price_seen": max_seen,
                    "opened_at": time.time() - opened_seconds_ago,
                }
            },
        }
    )


@pytest.mark.parametrize(
    "trail_env,mid_price,max_seen,expected_close",
    [
        # default 0.988: pullback to 101.2 from peak 101.5 does NOT trigger (101.2 > 100.28)
        (None, 101.2, 101.5, False),
        ("0.988", 101.2, 101.5, False),
        # hard trail 1.0: any pullback from the peak after +1% closes the position
        ("1.0", 101.2, 101.5, True),
    ],
)
def test_trail_ratio_from_env_controls_trailing_stop(
    monkeypatch, tmp_path, trail_env, mid_price, max_seen, expected_close
):
    monkeypatch.delenv("OCTOPUS_QUANT_ENTRY_MODE", raising=False)
    if trail_env is not None:
        monkeypatch.setenv("OCTOPUS_QUANT_TRAIL_RATIO", trail_env)
    else:
        monkeypatch.delenv("OCTOPUS_QUANT_TRAIL_RATIO", raising=False)
    engine = _engine(tmp_path, {"signal": "HOLD", "confidence": 0.5}, price=mid_price)
    data = engine.load_portfolios()
    _open_position(data, max_seen=max_seen)
    engine.save_portfolios(data)

    result = engine.run_multi_exchange_cycle()
    portfolio = engine.load_portfolios()["kraken"]

    if expected_close:
        closes = [t for t in result["cycle_trades"] if t["action"] == "CLOSE"]
        assert len(closes) == 1
        assert closes[0]["reason"] == "trailing_stop"
        assert portfolio["positions"] == {}
    else:
        assert portfolio["positions"].get("BTCUSD") is not None


def test_take_profit_and_stop_loss_from_env(monkeypatch, tmp_path):
    """TP/SL thresholds are configurable via env (fail-closed defaults preserved)."""
    monkeypatch.delenv("OCTOPUS_QUANT_ENTRY_MODE", raising=False)
    monkeypatch.setenv("OCTOPUS_QUANT_TAKE_PROFIT_PCT", "0.01")  # TP at +1%
    monkeypatch.setenv("OCTOPUS_QUANT_STOP_LOSS_PCT", "-0.005")  # SL at -0.5%
    # price +2.0% above entry: net +1.49% after costs — TP env 0.01 fires, default 2.0 would not
    engine = _engine(tmp_path, {"signal": "HOLD", "confidence": 0.5}, price=102.0)
    data = engine.load_portfolios()
    _open_position(data)
    engine.save_portfolios(data)

    result = engine.run_multi_exchange_cycle()
    portfolio = engine.load_portfolios()["kraken"]
    closes = [t for t in result["cycle_trades"] if t["action"] == "CLOSE"]
    assert len(closes) == 1
    assert closes[0]["reason"] == "take_profit"
    assert portfolio["positions"] == {}
    assert portfolio["closed_trades"] == 1
    assert portfolio["winning_trades"] == 1


def test_exit_params_defaults_preserve_legacy_behaviour():
    """Defaults must equal the pre-config values (2.0% / -1.0% / 0.988)."""
    from swarm.quant.quant_directional_policy import DirectionalV2Config

    cfg = DirectionalV2Config()
    assert cfg.take_profit_pct == 0.02
    assert cfg.stop_loss_pct == -0.01
    assert cfg.trail_ratio == 0.988
