from scripts.aios.research.run_quant_regime_v3 import rolling
from swarm.quant.quant_regime_v3 import REGIMES, compute_regime_features, correlation_clusters


def _rows(n=3000):
    price = 100.0
    rows = []
    for i in range(n):
        price *= 1.001 if i % 100 < 70 else 0.998
        rows.append({"timestamp": i * 3600000.0, "open": price, "high": price * 1.003, "low": price * 0.997, "close": price, "volume": 1000 + i % 50})
    return rows


def test_features_are_causal_and_classified():
    rows = _rows(300)
    features = compute_regime_features(rows)
    assert len(features) == len(rows)
    assert {item["regime"] for item in features} <= REGIMES
    assert all(0 <= item["atr_percentile"] <= 1 for item in features)


def test_clusters_group_correlated_series():
    clusters = correlation_clusters({"A": [1, 2, 3, 4], "B": [2, 4, 6, 8], "C": [1, -1, 1, -1]})
    assert clusters["A"] == clusters["B"]
    assert clusters["A"] != clusters["C"]


def test_rolling_produces_multiple_untouched_folds():
    rows = _rows()
    folds = rolling(rows, compute_regime_features(rows), train=1000, test=500)
    assert len(folds) == 4
    assert all(fold["end"] - fold["start"] == 500 for fold in folds)
    assert all("costs_x1_5" in fold for fold in folds)
