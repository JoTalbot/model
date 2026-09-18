#!/usr/bin/env python3
"""Offline rolling multi-fold, cost-stressed Regime Directional v3 backtest."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from swarm.quant.quant_regime_v3 import compute_regime_features, correlation_clusters

PREFERRED = ("kraken", "binance", "kucoin", "bitstamp", "mexc")


@dataclass(frozen=True)
class Params:
    strength: float
    max_atr_percentile: float
    take_profit: float
    stop_loss: float


def load_rows(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8") as stream:
        data = [
            {key: float(row[key]) for key in ("timestamp_ms", "open", "high", "low", "close", "volume")}
            for row in csv.DictReader(stream)
        ]
    return [dict(row, timestamp=row.pop("timestamp_ms")) for row in data]


def simulate(rows, features, params, start, end, cost_multiplier=1.0):
    fee, friction = 0.0015 * cost_multiplier, 0.001 * cost_multiplier
    cash, position, peak = 1_000.0, None, 1_000.0
    wins = closed = 0
    profit = loss = max_dd = 0.0
    for index in range(start, min(end, len(rows))):
        mid, feature = rows[index]["close"], features[index]
        eligible = (
            feature["regime"] == "trend_up"
            and feature["trend_strength"] >= params.strength
            and feature["atr_percentile"] <= params.max_atr_percentile
            and feature["volume_percentile"] >= 0.20
        )
        if position is None and eligible:
            invested = min(cash * 0.20, 200.0)
            execution = mid * (1 + friction)
            quantity = (invested - invested * fee) / execution
            cash -= invested
            position = {"qty": quantity, "invested": invested, "entry": mid, "max": mid}
        elif position is not None:
            position["max"] = max(position["max"], mid)
            proceeds = position["qty"] * mid * (1 - friction)
            net = proceeds - proceeds * fee
            pnl = net - position["invested"]
            pnl_pct = pnl / position["invested"] * 100
            leave_regime = feature["regime"] != "trend_up"
            trailing = position["max"] > position["entry"] * 1.01 and mid <= position["max"] * 0.988
            if pnl_pct >= params.take_profit or pnl_pct <= -params.stop_loss or trailing or leave_regime:
                cash += net
                closed += 1
                if pnl > 0:
                    wins += 1
                    profit += pnl
                else:
                    loss += abs(pnl)
                position = None
        equity = cash + (position["qty"] * mid if position else 0.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
    if position:
        mid = rows[min(end, len(rows)) - 1]["close"]
        net = position["qty"] * mid * (1 - friction) * (1 - fee)
        pnl = net - position["invested"]
        cash += net
        closed += 1
        if pnl > 0:
            wins += 1
            profit += pnl
        else:
            loss += abs(pnl)
    return {
        "net_return_pct": round((cash / 1_000.0 - 1) * 100, 6),
        "closed_trades": closed,
        "winning_trades": wins,
        "profit_factor": round(profit / loss, 6) if loss else (999.0 if profit else 0.0),
        "max_drawdown_pct": round(max_dd, 6),
    }


def grid():
    return [Params(*values) for values in itertools.product((25.0, 35.0, 45.0), (0.70, 0.85), (2.0, 3.0), (1.0, 1.5))]


def rolling(rows, features, train=2000, test=500):
    folds = []
    for test_start in range(train, len(rows) - test + 1, test):
        train_start = test_start - train
        scored = []
        for params in grid():
            result = simulate(rows, features, params, train_start, test_start)
            scored.append((result["net_return_pct"] - 0.25 * result["max_drawdown_pct"], params))
        params = max(scored, key=lambda item: item[0])[1]
        base = simulate(rows, features, params, test_start, test_start + test)
        stress = simulate(rows, features, params, test_start, test_start + test, cost_multiplier=1.5)
        folds.append(
            {
                "start": test_start,
                "end": test_start + test,
                "params": asdict(params),
                "base": base,
                "costs_x1_5": stress,
            }
        )
    return folds


def datasets(root: Path):
    for symbol_dir in sorted(path for path in root.iterdir() if path.is_dir() and path.name != "models"):
        for exchange in PREFERRED:
            path = symbol_dir / exchange / f"{symbol_dir.name}_1h.csv"
            if path.exists():
                rows = load_rows(path)
                if len(rows) >= 3000:
                    yield symbol_dir.name, exchange, path, rows
                    break


def generate(root: Path) -> dict[str, Any]:
    results, returns = [], {}
    for symbol, exchange, path, rows in datasets(root):
        closes = [row["close"] for row in rows]
        returns[symbol] = [(b / a - 1) for a, b in pairwise(closes) if a > 0]
        features = compute_regime_features(rows)
        folds = rolling(rows, features)
        results.append({"symbol": symbol, "exchange": exchange, "source": str(path), "rows": len(rows), "folds": folds})
    clusters = correlation_clusters(returns)
    fold_returns = [fold["base"]["net_return_pct"] for item in results for fold in item["folds"]]
    stress_returns = [fold["costs_x1_5"]["net_return_pct"] for item in results for fold in item["folds"]]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "strategy": "regime_directional_v3",
        "cost_model": "directional_v2",
        "walk_forward": True,
        "rolling_folds": True,
        "timeframe": "1h_closed",
        "assets": len(results),
        "folds": len(fold_returns),
        "summary": {
            "median_oos_return_pct": round(statistics.median(fold_returns), 6) if fold_returns else 0.0,
            "positive_fold_ratio": round(sum(value > 0 for value in fold_returns) / len(fold_returns), 6)
            if fold_returns
            else 0.0,
            "median_stress_return_pct": round(statistics.median(stress_returns), 6) if stress_returns else 0.0,
        },
        "correlation_clusters": clusters,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/quant"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/backtest_regime_v3.json"))
    args = parser.parse_args()
    report = generate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print(f"assets={report['assets']} folds={report['folds']} summary={report['summary']}")
    return 0 if report["assets"] >= 10 and report["folds"] >= 40 else 1


if __name__ == "__main__":
    raise SystemExit(main())
