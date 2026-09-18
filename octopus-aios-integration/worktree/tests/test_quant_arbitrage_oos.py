from scripts.aios.research.run_quant_arbitrage_oos import rolling, simulate


def _rows(n=3000, spread=0.02):
    return [(i, {"binance": 100.0, "kucoin": 100.0 * (1 + spread)}) for i in range(n)]


def test_next_candle_execution_and_costs():
    result = simulate(_rows(), 1.0, 0, 500)
    stressed = simulate(_rows(), 1.0, 0, 500, fee_rate=0.00225, slippage_rate=0.0015)
    assert result["trades"] > 0
    assert result["net_pnl_usd"] > stressed["net_pnl_usd"]


def test_rolling_has_untouched_folds():
    folds = rolling(_rows(), train=1000, test=500)
    assert len(folds) == 4
    assert all(fold["end"] - fold["start"] == 500 for fold in folds)
