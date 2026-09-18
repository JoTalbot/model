#!/usr/bin/env python3
"""Offline rolling OOS low-frequency trend portfolio; no orders/network."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.aios.research.run_quant_cross_sectional import panel


@dataclass(frozen=True)
class Params:
    fast: int
    slow: int
    rebalance: int
    max_assets: int


def simulate(prices, params, start, end, hours, cost_multiplier=1.0):
    equity = peak = 1000.0
    max_dd = 0.0
    weights = {}
    returns = []
    cost_rate = 0.0025 * cost_multiplier
    size = min(end, len(next(iter(prices.values()))) - 1)
    for index in range(max(start, params.slow), size):
        if (index - start) % params.rebalance == 0:
            candidates = []
            for symbol, values in prices.items():
                fast = statistics.mean(values[index - params.fast + 1 : index + 1])
                slow = statistics.mean(values[index - params.slow + 1 : index + 1])
                momentum = values[index] / values[index - params.fast] - 1
                recent = [values[j] / values[j - 1] - 1 for j in range(index - 19, index + 1)]
                vol = statistics.pstdev(recent) or 1e-9
                if values[index] > fast > slow and momentum > 0:
                    candidates.append((momentum / vol, symbol, vol))
            chosen = sorted(candidates, reverse=True)[: params.max_assets]
            inverse = {symbol: 1 / vol for _score, symbol, vol in chosen}
            total = sum(inverse.values())
            new_weights = {symbol: value / total for symbol, value in inverse.items()} if total else {}
            turnover = sum(
                abs(weights.get(symbol, 0) - new_weights.get(symbol, 0)) for symbol in set(weights) | set(new_weights)
            )
            equity *= 1 - turnover * cost_rate
            weights = new_weights
        period_return = sum(
            weight * (prices[symbol][index + 1] / prices[symbol][index] - 1) for symbol, weight in weights.items()
        )
        equity *= 1 + period_return
        returns.append(period_return)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
        if max_dd >= 3.0:
            weights = {}
    mean = statistics.mean(returns) if returns else 0.0
    std = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = mean / std * math.sqrt(365 * 24 / hours) if std else 0.0
    return {
        "net_return_pct": round((equity / 1000 - 1) * 100, 6),
        "max_drawdown_pct": round(max_dd, 6),
        "sharpe": round(sharpe, 6),
        "periods": len(returns),
    }


def grid(hours):
    if hours == 4:
        values = itertools.product((20, 30, 50), (80, 120, 200), (6, 21, 42), (3, 5))
    else:
        values = itertools.product((10, 20, 50), (50, 100, 150), (5, 7, 20), (3, 5))
    return [Params(*item) for item in values if item[0] < item[1]]


def rolling(prices, hours):
    size = len(next(iter(prices.values())))
    train, test = (500, 250) if hours == 4 else (100, 30)
    folds = []
    for test_start in range(train, size - test + 1, test):
        params = max(
            grid(hours), key=lambda p: simulate(prices, p, test_start - train, test_start, hours)["net_return_pct"]
        )
        folds.append(
            {
                "start": test_start,
                "end": test_start + test,
                "params": asdict(params),
                "base": simulate(prices, params, test_start, test_start + test, hours),
                "costs_x1_5": simulate(prices, params, test_start, test_start + test, hours, 1.5),
            }
        )
    return folds


def generate(root):
    results = []
    for hours in (4, 24):
        timestamps, prices = panel(root, hours)
        results.append(
            {
                "timeframe": f"{hours}h",
                "assets": len(prices),
                "bars": len(timestamps),
                "folds": rolling(prices, hours) if prices else [],
            }
        )
    folds = [fold for result in results for fold in result["folds"]]
    values = [fold["base"]["net_return_pct"] for fold in folds]
    stress = [fold["costs_x1_5"]["net_return_pct"] for fold in folds]
    return {
        "strategy": "low_frequency_trend",
        "walk_forward": True,
        "no_leverage": True,
        "results": results,
        "summary": {
            "folds": len(folds),
            "median_oos_return_pct": round(statistics.median(values), 6) if values else 0.0,
            "positive_ratio": round(sum(x > 0 for x in values) / len(values), 6) if values else 0.0,
            "median_stress_return_pct": round(statistics.median(stress), 6) if stress else 0.0,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/quant"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/backtest_low_frequency_trend.json"))
    args = parser.parse_args()
    report = generate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"]))
    return 0 if report["summary"]["folds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
