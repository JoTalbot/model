#!/usr/bin/env python3
"""Offline rolling OOS pairs/relative-value research; no orders/network."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
from itertools import pairwise
from pathlib import Path

from scripts.aios.research.run_quant_cross_sectional import panel


def fit(left, right, start, end):
    x, y = left[start:end], right[start:end]
    mx, my = statistics.mean(x), statistics.mean(y)
    var = sum((v - my) ** 2 for v in y)
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / var if var else 1.0
    spread = [math.log(a) - beta * math.log(b) for a, b in zip(x, y, strict=True)]
    mean, std = statistics.mean(spread), statistics.pstdev(spread)
    crossings = sum((a - mean) * (b - mean) < 0 for a, b in pairwise(spread))
    corr_num = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    corr_den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return {
        "beta": beta,
        "mean": mean,
        "std": std,
        "crossings": crossings,
        "correlation": corr_num / corr_den if corr_den else 0.0,
    }


def simulate(left, right, model, start, end, entry_z=2.0, exit_z=0.5, cost_multiplier=1.0):
    if model["std"] <= 0:
        return {"net_return_pct": 0.0, "trades": 0, "wins": 0, "profit_factor": 0.0, "max_drawdown_pct": 0.0}
    capital = peak = 1000.0
    position = None
    profits = losses = 0.0
    trades = wins = 0
    max_dd = 0.0
    round_trip_cost = 0.01 * cost_multiplier  # two legs, entry+exit
    for index in range(start, min(end, len(left))):
        spread = math.log(left[index]) - model["beta"] * math.log(right[index])
        z = (spread - model["mean"]) / model["std"]
        if position is None and abs(z) >= entry_z:
            position = {"direction": -1.0 if z > 0 else 1.0, "spread": spread}
        elif position is not None and (abs(z) <= exit_z or abs(z) >= 4.0 or index == end - 1):
            gross = position["direction"] * (spread - position["spread"])
            pnl_pct = gross * 100.0 - round_trip_cost * 100.0
            pnl = capital * pnl_pct / 100.0
            capital += pnl
            trades += 1
            if pnl > 0:
                wins += 1
                profits += pnl
            else:
                losses += abs(pnl)
            position = None
            peak = max(peak, capital)
            max_dd = max(max_dd, (peak - capital) / peak * 100.0)
    return {
        "net_return_pct": round((capital / 1000 - 1) * 100, 6),
        "trades": trades,
        "wins": wins,
        "profit_factor": round(profits / losses, 6) if losses else (999.0 if profits else 0.0),
        "max_drawdown_pct": round(max_dd, 6),
    }


def generate(root: Path):
    _timestamps, prices = panel(root, 4)
    size = len(next(iter(prices.values())))
    folds = []
    for test_start in range(500, size - 250 + 1, 250):
        candidates = []
        for left, right in itertools.combinations(sorted(prices), 2):
            model = fit(prices[left], prices[right], test_start - 500, test_start)
            if abs(model["correlation"]) >= 0.70 and model["crossings"] >= 8 and model["std"] > 0:
                candidates.append((model["crossings"] * abs(model["correlation"]), left, right, model))
        for _score, left, right, model in sorted(candidates, reverse=True)[:5]:
            params = max(
                itertools.product((1.5, 2.0, 2.5), (0.25, 0.5, 0.75)),
                key=lambda p: simulate(prices[left], prices[right], model, test_start - 500, test_start, *p)[
                    "net_return_pct"
                ],
            )
            folds.append(
                {
                    "fold_start": test_start,
                    "pair": f"{left}/{right}",
                    "model": model,
                    "entry_z": params[0],
                    "exit_z": params[1],
                    "base": simulate(prices[left], prices[right], model, test_start, test_start + 250, *params),
                    "costs_x1_5": simulate(
                        prices[left], prices[right], model, test_start, test_start + 250, *params, cost_multiplier=1.5
                    ),
                }
            )
    values = [x["base"]["net_return_pct"] for x in folds]
    stress = [x["costs_x1_5"]["net_return_pct"] for x in folds]
    return {
        "strategy": "pairs_relative_value",
        "walk_forward": True,
        "assets": len(prices),
        "folds": folds,
        "summary": {
            "evaluations": len(folds),
            "median_oos_return_pct": round(statistics.median(values), 6) if values else 0.0,
            "positive_ratio": round(sum(x > 0 for x in values) / len(values), 6) if values else 0.0,
            "median_stress_return_pct": round(statistics.median(stress), 6) if stress else 0.0,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/quant"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/backtest_pairs_oos.json"))
    args = parser.parse_args()
    report = generate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"]))
    return 0 if report["summary"]["evaluations"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
