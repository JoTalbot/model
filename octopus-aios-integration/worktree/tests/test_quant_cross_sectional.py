from scripts.aios.research.run_quant_cross_sectional import Params, simulate


def test_cross_sectional_simulation_cost_stress():
    prices = {f"S{i}": [100 * (1 + (i + 1) * 0.0002) ** j for j in range(800)] for i in range(6)}
    p = Params(42, 21, 3)
    base = simulate(prices, p, 100, 700)
    stress = simulate(prices, p, 100, 700, 1.5)
    assert base["periods"] > 0 and base["net_return_pct"] >= stress["net_return_pct"]
