import json
from pathlib import Path

import pytest

from swarm.quant.quant_trading_engine import (
    MultiExchangeQuantEngine,
    format_multi_exchange_demo_report,
    get_multi_exchange_demo_report,
)


def _state(exchange_cash=1000.0):
    data = {}
    for exchange in MultiExchangeQuantEngine.EXCHANGES:
        data[exchange] = {
            "initial_balance_usd": 1000.0,
            "cash_usd": exchange_cash,
            "realized_pnl_usd": exchange_cash - 1000.0,
            "total_trades": 0,
            "winning_trades": 0,
            "positions": {},
        }
    return data


def _write_state(tmp_path: Path, data: dict) -> None:
    (tmp_path / "multi_exchange_portfolios.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_report_excludes_legacy_simulated_arbitrage(monkeypatch, tmp_path):
    data = _state(exchange_cash=999.0)
    data["cross_arbitrage"] = {
        "total_arbitrage_trades": 58,
        "arbitrage_pnl_usd": 147.15078742,
        "history": [],
    }
    _write_state(tmp_path, data)

    monkeypatch.setattr(
        MultiExchangeQuantEngine, "fetch_all_exchange_prices", lambda self: {}
    )
    monkeypatch.setattr("swarm.quant.quant_trading_engine._load_ai_signals", dict)

    report = get_multi_exchange_demo_report(str(tmp_path))

    assert report["total_initial_balance_usd"] == 10_000.0
    assert report["total_equity_usd"] == 9_990.0
    assert report["exchange_pnl_usd"] == -10.0
    assert report["grand_total_pnl_usd"] == -10.0
    assert report["grand_return_pct"] == pytest.approx(-0.1)
    assert report["cross_arbitrage"]["pnl_usd"] == 0.0
    assert report["cross_arbitrage"]["total_trades"] == 0
    assert report["cross_arbitrage"]["legacy_simulated_pnl_usd"] == pytest.approx(
        147.15078742
    )
    assert report["profit_split_25_usd"] == 0.0
    # Reading a report is accounting-only and must not mutate/migrate live state.
    persisted = json.loads((tmp_path / "multi_exchange_portfolios.json").read_text())
    assert persisted["cross_arbitrage"]["arbitrage_pnl_usd"] == pytest.approx(
        147.15078742
    )
    assert "legacy_simulated_pnl_usd" not in persisted["cross_arbitrage"]


def test_settled_arbitrage_is_attribution_not_a_second_equity_credit(
    monkeypatch, tmp_path
):
    data = _state(exchange_cash=1001.0)
    data["cross_arbitrage"] = {
        "accounting_version": 2,
        "settled_trades": 1,
        "settled_pnl_usd": 10.0,
        "legacy_simulated_trades": 58,
        "legacy_simulated_pnl_usd": 147.15078742,
        "history": [],
    }
    _write_state(tmp_path, data)
    monkeypatch.setattr(
        MultiExchangeQuantEngine, "fetch_all_exchange_prices", lambda self: {}
    )
    monkeypatch.setattr("swarm.quant.quant_trading_engine._load_ai_signals", dict)

    report = get_multi_exchange_demo_report(str(tmp_path))

    # The $10 settled attribution is already reflected by 10 exchange cash deltas.
    assert report["total_equity_usd"] == 10_010.0
    assert report["grand_total_pnl_usd"] == 10.0
    assert report["cross_arbitrage"]["pnl_usd"] == 10.0


def test_scan_migrates_legacy_accumulator_without_new_income(monkeypatch, tmp_path):
    data = _state()
    data["cross_arbitrage"] = {
        "total_arbitrage_trades": 58,
        "arbitrage_pnl_usd": 147.15078742,
        "history": [],
    }
    _write_state(tmp_path, data)

    engine = MultiExchangeQuantEngine(str(tmp_path))
    prices = {exchange: {} for exchange in engine.EXCHANGES}
    prices["binance"]["BTC"] = 100.0
    prices["bybit"]["BTC"] = 101.0
    monkeypatch.setattr(engine, "fetch_all_exchange_prices", lambda: prices)
    monkeypatch.setattr(
        engine.signal_engine,
        "record_and_analyze",
        lambda symbol, price: {"signal": "HOLD"},
    )

    engine.run_multi_exchange_cycle()
    saved = json.loads((tmp_path / "multi_exchange_portfolios.json").read_text())
    arb = saved["cross_arbitrage"]

    assert arb["accounting_version"] == 2
    assert arb["legacy_simulated_trades"] == 58
    assert arb["legacy_simulated_pnl_usd"] == pytest.approx(147.15078742)
    assert arb["total_arbitrage_trades"] == 0
    assert arb["arbitrage_pnl_usd"] == 0.0
    assert arb["settled_trades"] == 0
    assert arb["settled_pnl_usd"] == 0.0
    assert arb["last_scan_opportunities"] == 1
    assert arb["last_scan_theoretical_pnl_usd"] == pytest.approx(0.50)
    assert arb["history"][-1]["executed"] is False
    assert arb["history"][-1]["kind"] == "theoretical_opportunity"
    assert arb["history"][-1]["quote_currency"] == "USDT"


def test_scan_does_not_compare_usd_with_usdt(monkeypatch, tmp_path):
    data = _state()
    data["cross_arbitrage"] = {}
    _write_state(tmp_path, data)

    engine = MultiExchangeQuantEngine(str(tmp_path))
    prices = {exchange: {} for exchange in engine.EXCHANGES}
    prices["kraken"]["BTC"] = 100.0  # USD
    prices["binance"]["BTC"] = 110.0  # USDT
    monkeypatch.setattr(engine, "fetch_all_exchange_prices", lambda: prices)
    monkeypatch.setattr(
        engine.signal_engine,
        "record_and_analyze",
        lambda symbol, price: {"signal": "HOLD"},
    )

    engine.run_multi_exchange_cycle()
    saved = json.loads((tmp_path / "multi_exchange_portfolios.json").read_text())
    assert saved["cross_arbitrage"]["last_scan_opportunities"] == 0
    assert saved["cross_arbitrage"]["history"] == []


def test_format_is_dynamic_and_discloses_non_accounting_signal():
    report = {
        "exchange_count": 10,
        "initial_per_exchange_usd": 1000.0,
        "total_initial_balance_usd": 10_000.0,
        "total_cash_usd": 9_900.0,
        "total_equity_usd": 9_990.0,
        "grand_total_pnl_usd": -10.0,
        "grand_return_pct": -0.1,
        "exchanges": {},
        "cross_arbitrage": {
            "total_trades": 0,
            "pnl_usd": 0.0,
            "last_scan_opportunities": 2,
            "last_scan_theoretical_pnl_usd": 1.23,
            "legacy_simulated_pnl_usd": 147.15,
            "recent_trades": [],
        },
    }

    text = format_multi_exchange_demo_report(report)

    assert "10 бирж" in text
    assert "$10,000.00" in text
    assert "только equity/исполненное" in text
    assert "не считаются прибылью" in text
    assert "исключена из PnL" in text
    assert "$5,000" not in text


def test_ccxt_ticker_filter_rejects_recent_but_illiquid_last_trade():
    now_ms = 1_000_000.0
    stale_atom_shape = {
        "timestamp": now_ms - 1_000.0,
        "last": 1.3189,
        "bid": 1.0788,
        "ask": 3.4357,
        "baseVolume": 0.0,
        "quoteVolume": 0.0,
    }
    healthy = {
        "timestamp": now_ms - 1_000.0,
        "last": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "baseVolume": 50.0,
        "quoteVolume": 5_000.0,
    }
    old = dict(healthy, timestamp=now_ms - 120_001.0)

    assert not MultiExchangeQuantEngine._is_current_liquid_ticker(
        stale_atom_shape, now_ms=now_ms
    )
    assert not MultiExchangeQuantEngine._is_current_liquid_ticker(old, now_ms=now_ms)
    assert MultiExchangeQuantEngine._is_current_liquid_ticker(healthy, now_ms=now_ms)


def test_report_prefers_v2_state_and_uses_closed_trade_win_rate(monkeypatch, tmp_path):
    old = _state()
    _write_state(tmp_path, old)
    v2 = _state()
    v2["kraken"].update(
        {
            "entry_count": 10,
            "total_trades": 10,
            "closed_trades": 8,
            "winning_trades": 4,
            "gross_pnl_usd": 5.0,
            "fees_paid_usd": 2.0,
            "execution_costs_usd": 1.0,
            "net_profit_usd": 24.0,
            "net_loss_usd": 20.0,
        }
    )
    (tmp_path / "multi_exchange_portfolios_v2.json").write_text(
        json.dumps(v2), encoding="utf-8"
    )
    monkeypatch.setattr(
        MultiExchangeQuantEngine, "fetch_all_exchange_prices", lambda self: {}
    )
    monkeypatch.setattr("swarm.quant.quant_trading_engine._load_ai_signals", dict)

    report = get_multi_exchange_demo_report(str(tmp_path))

    assert report["portfolio_file"] == "multi_exchange_portfolios_v2.json"
    assert report["entry_count"] == 10
    assert report["closed_trades"] == 8
    assert report["winning_trades"] == 4
    assert report["win_rate_pct"] == pytest.approx(50.0)
    assert report["gross_pnl_usd"] == pytest.approx(5.0)
    assert report["fees_paid_usd"] == pytest.approx(2.0)
    assert report["execution_costs_usd"] == pytest.approx(1.0)
    assert report["net_profit_usd"] == pytest.approx(24.0)
    assert report["net_loss_usd"] == pytest.approx(20.0)
    assert report["profit_factor"] == pytest.approx(1.2)
