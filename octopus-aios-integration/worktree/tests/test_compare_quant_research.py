import json

from scripts.aios.research.compare_quant_research import compare


def test_comparison_defaults_to_monitoring_only(tmp_path):
    (tmp_path / "backtest_cross_sectional.json").write_text(
        json.dumps({"summary": {"positive_ratio": 0.3, "median_oos_return_pct": -1}})
    )
    r = compare(tmp_path)
    assert not r["ready"]
    assert r["runtime_mode"] == "monitoring_only"
    assert not r["passed_strategies"]
