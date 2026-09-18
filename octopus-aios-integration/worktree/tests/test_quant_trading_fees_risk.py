"""Тесты учёта комиссий и риск-фильтров PaperTradingSimulator / MultiExchangeQuantEngine."""

import pytest

from swarm.quant.quant_trading_engine import (
    MultiExchangeQuantEngine,
    PaperTradingSimulator,
)


def _buy_signal(symbol: str = "BTCUSD", price: float = 100.0) -> dict:
    return {"symbol": symbol, "current_price": price, "signal": "BUY_LONG"}


def _hold_signal(symbol: str = "BTCUSD", price: float = 100.0) -> dict:
    return {"symbol": symbol, "current_price": price, "signal": "HOLD"}


def test_buy_long_deducts_entry_fee(tmp_path):
    sim = PaperTradingSimulator(data_dir=str(tmp_path), initial_balance=1000.0)
    res = sim.execute_paper_signal(_buy_signal(price=100.0))

    assert res["trade"]["executed"] is True
    assert res["trade"]["action"] == "OPEN_LONG"
    # max_invest = min(1000 * 0.20, 200) = 200; fee = 200 * 0.0015 = 0.3
    assert res["portfolio_summary"]["cash_usd"] == pytest.approx(800.0)

    port = sim.load_portfolio()
    pos = port["positions"]["BTCUSD"]
    assert pos["entry_fee_usd"] == pytest.approx(0.3)
    assert pos["qty"] == pytest.approx((200.0 - 0.3) / 100.0)
    assert pos["invested_usd"] == pytest.approx(200.0)


def test_close_long_deducts_exit_fee_and_reports_total_fees(tmp_path):
    sim = PaperTradingSimulator(data_dir=str(tmp_path), initial_balance=1000.0)
    sim.execute_paper_signal(_buy_signal(price=100.0))

    # Цена +3%: net PnL = 1.997*103 - 1.997*103*0.0015 - 200 = 5.382...  -> +2.69% >= TP 2%
    res = sim.execute_paper_signal(_hold_signal(price=103.0))

    assert res["trade"]["executed"] is True
    assert res["trade"]["action"] == "CLOSE_LONG"
    assert res["trade"]["reason"].startswith("🎯 TAKE-PROFIT")

    qty = 1.997
    gross_value = qty * 103.0
    exit_fee = gross_value * sim.FEE_RATE
    net_value = gross_value - exit_fee
    pnl = net_value - 200.0

    assert res["trade"]["pnl_usd"] == pytest.approx(pnl, abs=0.01)
    assert res["trade"]["fees_usd"] == pytest.approx(0.3 + exit_fee)
    # кэш = 800 (после покупки) + net_value при закрытии (округлён до центов в сводке)
    assert res["portfolio_summary"]["cash_usd"] == pytest.approx(
        800.0 + net_value, abs=0.011
    )
    assert res["portfolio_summary"]["realized_pnl_usd"] == pytest.approx(pnl, abs=0.011)
    assert res["portfolio_summary"]["open_positions"] == 0


def test_buy_blocked_when_cash_below_reserve(tmp_path):
    sim = PaperTradingSimulator(data_dir=str(tmp_path), initial_balance=1000.0)
    port = sim.load_portfolio()
    port["cash_usd"] = 250.0  # ниже резерва 30% от 1000 = 300
    sim.save_portfolio(port)

    res = sim.execute_paper_signal(_buy_signal(price=100.0))

    assert res["trade"]["executed"] is False
    assert "Риск-фильтр" in res["trade"]["details"]
    assert res["portfolio_summary"]["open_positions"] == 0
    assert sim.load_portfolio()["positions"] == {}


def test_buy_blocked_at_position_limit(tmp_path):
    sim = PaperTradingSimulator(data_dir=str(tmp_path), initial_balance=1000.0)
    # Открываем 5 позиций по разным символам
    for i in range(5):
        r = sim.execute_paper_signal(_buy_signal(symbol=f"SYM{i}USD", price=100.0))
        assert r["trade"]["executed"] is True

    res = sim.execute_paper_signal(_buy_signal(symbol="SIXTHUSD", price=100.0))
    assert res["trade"]["executed"] is False
    assert "Риск-фильтр" in res["trade"]["details"]
    assert res["portfolio_summary"]["open_positions"] == 5


def test_multi_exchange_engine_has_risk_attributes():
    """Регрессия: атрибуты риск-фильтров должны быть определены в классе."""
    assert MultiExchangeQuantEngine.MAX_OPEN_POSITIONS_PER_EXCHANGE == 5
    assert pytest.approx(0.30) == MultiExchangeQuantEngine.MIN_CASH_RESERVE_PCT
    assert pytest.approx(0.0015) == MultiExchangeQuantEngine.FEE_RATE
    assert pytest.approx(0.60) == MultiExchangeQuantEngine.MIN_NET_ARBITRAGE_SPREAD_PCT


def test_multi_exchange_buy_deducts_fee(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOPUS_QUANT_ENTRY_MODE", "enabled")
    monkeypatch.setenv("OCTOPUS_QUANT_HALF_SPREAD_RATE", "0")
    monkeypatch.setenv("OCTOPUS_QUANT_SLIPPAGE_RATE", "0")
    eng = MultiExchangeQuantEngine(data_dir=str(tmp_path))
    data = eng.load_portfolios()
    data["kraken"]["cash_usd"] = 1000.0
    data["kraken"]["initial_balance_usd"] = 1000.0
    eng.save_portfolios(data)

    # Напрямую эмулируем buy-ветку: цена + сигнал BUY_LONG через фейковый signal engine
    class FakeSE:
        def load_history(self):
            return {}

        def save_history(self, hist):
            pass

        def record_and_analyze(self, symbol, price):
            return {
                "signal": "BUY_LONG",
                "confidence": 0.90,
                "ml_prob_up": 0.70,
                "rl_position": 0.60,
            }

    eng.signal_engine = FakeSE()
    eng.fetch_all_exchange_prices = lambda: {"kraken": {"BTC": 100.0}}

    eng.run_multi_exchange_cycle()

    data = eng.load_portfolios()
    pos = data["kraken"]["positions"]["BTCUSD"]
    assert pos["entry_fee_usd"] == pytest.approx(0.3)
    assert pos["qty"] == pytest.approx(199.7 / 100.0)
    assert data["kraken"]["cash_usd"] == pytest.approx(800.0)
