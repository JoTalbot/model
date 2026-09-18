#!/usr/bin/env python3
"""Offline rolling OOS cross-sectional momentum research; no orders/network."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "POL", "LTC", "ATOM", "NEAR", "ARB")


@dataclass(frozen=True)
class Params:
    lookback: int
    rebalance: int
    top_n: int


def load_hourly(root: Path, symbol: str) -> dict[int, float]:
    path = root / symbol / "binance" / f"{symbol}_1h.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as stream:
        return {
            int(row["timestamp_ms"]): float(row["close"]) for row in csv.DictReader(stream) if float(row["close"]) > 0
        }


def panel(root: Path, hours: int) -> tuple[list[int], dict[str, list[float]]]:
    raw = {symbol: load_hourly(root, symbol) for symbol in SYMBOLS}
    bucketed = {}
    bucket_ms = hours * 3_600_000
    for symbol, values in raw.items():
        buckets = {}
        for timestamp, close in values.items():
            buckets[timestamp // bucket_ms * bucket_ms] = close
        bucketed[symbol] = buckets
    valid = {symbol: values for symbol, values in bucketed.items() if len(values) >= 150}
    timestamps = sorted(set.intersection(*(set(values) for values in valid.values()))) if len(valid) >= 5 else []
    return timestamps, {symbol: [values[timestamp] for timestamp in timestamps] for symbol, values in valid.items()}


def correlation(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size < 3:
        return 0.0
    a, b = left[-size:], right[-size:]
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def simulate(prices: dict[str, list[float]], params: Params, start: int, end: int, cost_multiplier=1.0):
    equity = peak = 1_000.0
    max_dd = 0.0
    holdings: list[str] = []
    period_returns = []
    cost_rate = 0.0025 * cost_multiplier
    symbols = sorted(prices)
    for index in range(max(start, params.lookback), min(end, len(next(iter(prices.values())))) - 1):
        if (index - start) % params.rebalance == 0:
            scores = sorted(
                ((prices[s][index] / prices[s][index - params.lookback] - 1, s) for s in symbols), reverse=True
            )
            selected = []
            returns = {
                s: [prices[s][j] / prices[s][j - 1] - 1 for j in range(index - params.lookback + 1, index + 1)]
                for s in symbols
            }
            for _score, symbol in scores:
                if all(abs(correlation(returns[symbol], returns[other])) < 0.85 for other in selected):
                    selected.append(symbol)
                if len(selected) == params.top_n:
                    break
            turnover = len(set(holdings) ^ set(selected)) / max(1, params.top_n)
            equity *= 1.0 - turnover * cost_rate
            holdings = selected
        if holdings:
            value = statistics.mean(prices[s][index + 1] / prices[s][index] - 1 for s in holdings)
            equity *= 1.0 + value
            period_returns.append(value)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    mean = statistics.mean(period_returns) if period_returns else 0.0
    std = statistics.pstdev(period_returns) if len(period_returns) > 1 else 0.0
    sharpe = mean / std * math.sqrt(365 * 6) if std else 0.0
    return {
        "net_return_pct": round((equity / 1000 - 1) * 100, 6),
        "max_drawdown_pct": round(max_dd, 6),
        "sharpe": round(sharpe, 6),
        "periods": len(period_returns),
    }


def grid(hours: int):
    lookbacks = (42, 84, 126) if hours == 4 else (20, 60, 120)
    rebalances = (6, 21, 42) if hours == 4 else (5, 7, 20)
    return [Params(*values) for values in itertools.product(lookbacks, rebalances, (2, 3, 5))]


def rolling(prices, hours):
    size = len(next(iter(prices.values())))
    train, test = (500, 250) if hours == 4 else (100, 30)
    folds = []
    for test_start in range(train, size - test + 1, test):
        train_start = test_start - train
        params = max(grid(hours), key=lambda p: simulate(prices, p, train_start, test_start)["net_return_pct"])
        folds.append(
            {
                "start": test_start,
                "end": test_start + test,
                "params": asdict(params),
                "base": simulate(prices, params, test_start, test_start + test),
                "costs_x1_5": simulate(prices, params, test_start, test_start + test, 1.5),
            }
        )
    return folds


def generate(root: Path) -> dict[str, Any]:
    results = []
    for hours in (4, 24):
        timestamps, prices = panel(root, hours)
        folds = rolling(prices, hours) if prices else []
        results.append({"timeframe": f"{hours}h", "assets": len(prices), "bars": len(timestamps), "folds": folds})
    all_folds = [fold for result in results for fold in result["folds"]]
    returns = [fold["base"]["net_return_pct"] for fold in all_folds]
    stress = [fold["costs_x1_5"]["net_return_pct"] for fold in all_folds]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "strategy": "cross_sectional_momentum",
        "walk_forward": True,
        "results": results,
        "summary": {
            "folds": len(all_folds),
            "median_oos_return_pct": round(statistics.median(returns), 6) if returns else 0.0,
            "positive_fold_ratio": round(sum(x > 0 for x in returns) / len(returns), 6) if returns else 0.0,
            "median_stress_return_pct": round(statistics.median(stress), 6) if stress else 0.0,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/quant"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/backtest_cross_sectional.json"))
    args = parser.parse_args()
    report = generate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"]))
    return 0 if report["summary"]["folds"] >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
