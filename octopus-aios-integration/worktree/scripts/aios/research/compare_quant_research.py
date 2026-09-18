#!/usr/bin/env python3
"""Compare offline research artifacts and enforce monitoring-only when none pass."""

import argparse
import json
from pathlib import Path


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def compare(root):
    specs = {
        "regime_v3": ("backtest_regime_v3.json", "positive_fold_ratio", "median_oos_return_pct"),
        "arbitrage": ("backtest_arbitrage_oos.json", "positive_fold_ratio", "net_pnl_usd"),
        "cross_sectional": ("backtest_cross_sectional.json", "positive_ratio", "median_oos_return_pct"),
        "pairs": ("backtest_pairs_oos.json", "positive_ratio", "median_oos_return_pct"),
        "low_frequency_trend": ("backtest_low_frequency_trend.json", "positive_ratio", "median_oos_return_pct"),
    }
    results = {}
    for name, (file, ratio_key, return_key) in specs.items():
        d = load(root / file)
        s = d.get("summary", {})
        ratio = float(s.get(ratio_key, 0) or 0)
        value = float(s.get(return_key, 0) or 0)
        results[name] = {
            "available": bool(d),
            "positive_ratio": ratio,
            "return_metric": value,
            "passed": bool(d) and ratio >= 0.75 and value > 0,
        }
    mm = load(root / "market_making_simulation.json")
    results["market_making"] = {
        "available": bool(mm),
        "passed": bool(mm.get("ready")),
        "samples": mm.get("total_snapshots", 0),
    }
    defi = load(root / "defi_yield_gate.json")
    results["defi_yield"] = {"available": bool(defi), "passed": bool(defi.get("ready"))}
    passed = [k for k, v in results.items() if v["passed"]]
    return {
        "ready": bool(passed),
        "passed_strategies": passed,
        "runtime_mode": "research_candidate" if passed else "monitoring_only",
        "results": results,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("data/reports"))
    p.add_argument("--output", type=Path, default=Path("data/reports/quant_research_comparison.json"))
    a = p.parse_args()
    r = compare(a.root)
    a.output.write_text(json.dumps(r, indent=2) + "\n")
    print(f"ready={r['ready']} mode={r['runtime_mode']} passed={r['passed_strategies']}")
    return 0 if r["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
