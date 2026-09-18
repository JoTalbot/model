from scripts.aios.research.run_quant_low_frequency_trend import Params, simulate


def test_low_frequency_trend_cost_stress():
    prices = {f"S{i}": [100 * (1 + (i + 1) * 0.0001) ** j for j in range(800)] for i in range(6)}
    p = Params(20, 80, 21, 3)
    base = simulate(prices, p, 100, 700, 4)
    stress = simulate(prices, p, 100, 700, 4, 1.5)
    assert base["periods"] > 0 and base["net_return_pct"] >= stress["net_return_pct"]
    assert base["max_drawdown_pct"] <= 3.1
