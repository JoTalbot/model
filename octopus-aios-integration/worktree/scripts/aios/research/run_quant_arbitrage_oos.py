#!/usr/bin/env python3
"""Offline rolling OOS cross-exchange arbitrage simulator; no orders/network."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXCHANGES = ("binance", "kucoin", "mexc")
THRESHOLDS = (0.8, 1.0, 1.2, 1.5, 2.0)


def load(path: Path) -> dict[int, float]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {
            int(row["timestamp_ms"]): float(row["close"]) for row in csv.DictReader(stream) if float(row["close"]) > 0
        }


def aligned(root: Path, symbol: str) -> list[tuple[int, dict[str, float]]]:
    series = {}
    for exchange in EXCHANGES:
        path = root / symbol / exchange / f"{symbol}_1h.csv"
        if path.exists():
            series[exchange] = load(path)
    best_names = ()
    best_timestamps = []
    names = sorted(series)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            timestamps = sorted(set(series[left]) & set(series[right]))
            if len(timestamps) > len(best_timestamps):
                best_names = (left, right)
                best_timestamps = timestamps
    return [
        (timestamp, {exchange: series[exchange][timestamp] for exchange in best_names}) for timestamp in best_timestamps
    ]


def simulate(rows, threshold, start, end, *, trade_usd=100.0, fee_rate=0.0015, slippage_rate=0.001):
    pnls = []
    cooldown_until = -1
    for index in range(start, min(end, len(rows) - 1)):
        if index < cooldown_until:
            continue
        current, following = rows[index][1], rows[index + 1][1]
        buy_exchange, sell_exchange = min(current, key=current.get), max(current, key=current.get)
        gross_spread = (current[sell_exchange] / current[buy_exchange] - 1.0) * 100.0
        if gross_spread < threshold:
            continue
        buy_price = following[buy_exchange] * (1.0 + slippage_rate)
        sell_price = following[sell_exchange] * (1.0 - slippage_rate)
        quantity = trade_usd / buy_price
        gross_proceeds = quantity * sell_price
        net = gross_proceeds * (1.0 - fee_rate) - trade_usd * (1.0 + fee_rate)
        pnls.append(net)
        cooldown_until = index + 6
    profits = sum(value for value in pnls if value > 0)
    losses = sum(abs(value) for value in pnls if value < 0)
    return {
        "trades": len(pnls),
        "net_pnl_usd": round(sum(pnls), 6),
        "wins": sum(value > 0 for value in pnls),
        "profit_factor": round(profits / losses, 6) if losses else (999.0 if profits else 0.0),
    }


def rolling(rows, train=2000, test=500):
    folds = []
    for test_start in range(train, len(rows) - test + 1, test):
        train_start = test_start - train
        threshold = max(THRESHOLDS, key=lambda value: simulate(rows, value, train_start, test_start)["net_pnl_usd"])
        result = simulate(rows, threshold, test_start, test_start + test)
        stress = simulate(rows, threshold, test_start, test_start + test, fee_rate=0.00225, slippage_rate=0.0015)
        folds.append(
            {
                "start": test_start,
                "end": test_start + test,
                "threshold_pct": threshold,
                "base": result,
                "costs_x1_5": stress,
            }
        )
    return folds


def generate(root: Path) -> dict[str, Any]:
    results = []
    for symbol_dir in sorted(path for path in root.iterdir() if path.is_dir() and path.name != "models"):
        rows = aligned(root, symbol_dir.name)
        if len(rows) >= 3000:
            results.append({"symbol": symbol_dir.name, "rows": len(rows), "folds": rolling(rows)})
    folds = [fold for item in results for fold in item["folds"]]
    pnls = [fold["base"]["net_pnl_usd"] for fold in folds]
    stress = [fold["costs_x1_5"]["net_pnl_usd"] for fold in folds]
    trades = sum(fold["base"]["trades"] for fold in folds)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "strategy": "cross_exchange_arbitrage_oos",
        "execution": "signal_t_execute_t_plus_1",
        "quote_currency": "USDT_only",
        "walk_forward": True,
        "assets": len(results),
        "folds": len(folds),
        "summary": {
            "net_pnl_usd": round(sum(pnls), 6),
            "median_fold_pnl_usd": round(statistics.median(pnls), 6) if pnls else 0.0,
            "positive_fold_ratio": round(sum(value > 0 for value in pnls) / len(pnls), 6) if pnls else 0.0,
            "stress_net_pnl_usd": round(sum(stress), 6),
            "trades": trades,
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/quant"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/backtest_arbitrage_oos.json"))
    args = parser.parse_args()
    report = generate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"assets={report['assets']} folds={report['folds']} summary={report['summary']}")
    return 0 if report["assets"] >= 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
