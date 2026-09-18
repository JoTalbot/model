#!/usr/bin/env python3
"""Offline cost-aware walk-forward backtest for Directional v2."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

PREFERRED_EXCHANGES = ("kraken", "binance", "kucoin", "bitstamp", "mexc", "bybit", "okx")


@dataclass(frozen=True)
class Params:
    fast: int
    slow: int
    rsi_low: float
    take_profit: float
    stop_loss: float


def load_ohlcv(path: Path) -> list[dict[str, float]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            try:
                rows.append(
                    {
                        "timestamp": float(row["timestamp_ms"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    unique = {int(row["timestamp"]): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def _sma(values: list[float], end: int, window: int) -> float:
    chunk = values[end - window + 1 : end + 1]
    return statistics.mean(chunk) if len(chunk) == window else math.nan


def _rsi(values: list[float], end: int, window: int = 14) -> float:
    chunk = values[end - window : end + 1]
    if len(chunk) < window + 1:
        return 50.0
    gains = [max(0.0, b - a) for a, b in pairwise(chunk)]
    losses = [max(0.0, a - b) for a, b in pairwise(chunk)]
    avg_gain, avg_loss = statistics.mean(gains), statistics.mean(losses)
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def simulate(
    rows: list[dict[str, float]],
    params: Params,
    *,
    trade_start: int = 0,
    fee_rate: float = 0.0015,
    half_spread_rate: float = 0.0005,
    slippage_rate: float = 0.0005,
) -> dict[str, float | int]:
    closes = [row["close"] for row in rows]
    cash, initial = 1_000.0, 1_000.0
    position = None
    wins = closed = 0
    net_profit = net_loss = fees = execution_costs = 0.0
    peak = initial
    max_drawdown = 0.0
    start = max(params.slow, 20, trade_start)

    for index in range(start, len(rows)):
        mid = closes[index]
        fast, slow = _sma(closes, index, params.fast), _sma(closes, index, params.slow)
        rsi = _rsi(closes, index)
        recent = closes[index - 19 : index + 1]
        mean, std = statistics.mean(recent), statistics.pstdev(recent)
        bullish = (2 if mid <= mean - 2 * std else 0) + (2 if rsi < params.rsi_low else 0) + (1 if fast > slow else 0)
        bearish = (2 if mid >= mean + 2 * std else 0) + (2 if rsi > 65 else 0) + (1 if fast < slow else 0)

        if position is None and index >= trade_start and bullish >= 3:
            investment = min(cash * 0.20, 200.0)
            if investment >= 10:
                fee = investment * fee_rate
                execution = mid * (1 + half_spread_rate + slippage_rate)
                qty = (investment - fee) / execution
                costs = qty * (execution - mid)
                position = {"qty": qty, "invested": investment, "entry_mid": mid, "max": mid}
                cash -= investment
                fees += fee
                execution_costs += costs
        elif position is not None:
            position["max"] = max(position["max"], mid)
            execution = mid * (1 - half_spread_rate - slippage_rate)
            proceeds = position["qty"] * execution
            fee = proceeds * fee_rate
            net = proceeds - fee
            pnl = net - position["invested"]
            pnl_pct = pnl / position["invested"] * 100
            trailing = position["max"] > position["entry_mid"] * 1.01 and mid <= position["max"] * 0.988
            if pnl_pct >= params.take_profit or pnl_pct <= -params.stop_loss or trailing or bearish >= 3:
                cash += net
                fees += fee
                execution_costs += position["qty"] * (mid - execution)
                closed += 1
                if pnl > 0:
                    wins += 1
                    net_profit += pnl
                else:
                    net_loss += abs(pnl)
                position = None

        equity = cash + (position["qty"] * mid if position else 0.0)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100 if peak > 0 else 0.0)

    if position is not None:
        mid = closes[-1]
        execution = mid * (1 - half_spread_rate - slippage_rate)
        proceeds = position["qty"] * execution
        fee = proceeds * fee_rate
        pnl = proceeds - fee - position["invested"]
        cash += proceeds - fee
        fees += fee
        execution_costs += position["qty"] * (mid - execution)
        closed += 1
        if pnl > 0:
            wins += 1
            net_profit += pnl
        else:
            net_loss += abs(pnl)

    net_return = (cash / initial - 1.0) * 100.0
    return {
        "net_return_pct": round(net_return, 6),
        "closed_trades": closed,
        "winning_trades": wins,
        "win_rate_pct": round(wins / closed * 100, 6) if closed else 0.0,
        "net_profit_usd": round(net_profit, 8),
        "net_loss_usd": round(net_loss, 8),
        "profit_factor": round(net_profit / net_loss, 6) if net_loss > 0 else (999.0 if net_profit > 0 else 0.0),
        "fees_usd": round(fees, 8),
        "execution_costs_usd": round(execution_costs, 8),
        "max_drawdown_pct": round(max_drawdown, 6),
    }


def parameter_grid():
    for values in itertools.product((3, 5), (10, 20), (30.0, 35.0), (1.5, 2.0, 2.5), (0.8, 1.0, 1.2)):
        fast, slow, rsi, take, stop = values
        if fast < slow:
            yield Params(fast, slow, rsi, take, stop)


def walk_forward(rows: list[dict[str, float]]) -> dict[str, Any]:
    split = int(len(rows) * 0.70)
    train = rows[:split]
    scored = []
    for params in parameter_grid():
        result = simulate(train, params)
        score = float(result["net_return_pct"]) - 0.25 * float(result["max_drawdown_pct"])
        scored.append((score, params, result))
    _score, best, train_result = max(scored, key=lambda item: item[0])
    test_result = simulate(rows, best, trade_start=split)
    return {
        "rows": len(rows),
        "train_rows": split,
        "test_rows": len(rows) - split,
        "params": asdict(best),
        "train": train_result,
        "test": test_result,
    }


def select_datasets(root: Path, min_rows: int = 400) -> list[tuple[str, str, Path, list[dict[str, float]]]]:
    selected = []
    for symbol_dir in sorted(path for path in root.iterdir() if path.is_dir() and path.name != "models"):
        for exchange in PREFERRED_EXCHANGES:
            path = symbol_dir / exchange / f"{symbol_dir.name}_1h.csv"
            if not path.exists():
                continue
            rows = load_ohlcv(path)
            if len(rows) >= min_rows:
                selected.append((symbol_dir.name, exchange, path, rows))
                break
    return selected


def generate(root: Path) -> dict[str, Any]:
    results = []
    for symbol, exchange, path, rows in select_datasets(root):
        result = walk_forward(rows)
        test = result["test"]
        results.append({"symbol": symbol, "exchange": exchange, "source": str(path), **result, **test})
    returns = [float(row["net_return_pct"]) for row in results]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "cost_model": "directional_v2",
        "walk_forward": True,
        "timeframe": "1h_closed",
        "train_ratio": 0.70,
        "fee_rate_per_side": 0.0015,
        "half_spread_rate_per_side": 0.0005,
        "slippage_rate_per_side": 0.0005,
        "assets": len(results),
        "summary": {
            "average_net_return_pct": round(statistics.mean(returns), 6) if returns else 0.0,
            "median_net_return_pct": round(statistics.median(returns), 6) if returns else 0.0,
            "positive_assets": sum(value > 0 for value in returns),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/quant"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/backtest_directional_v2.json"))
    args = parser.parse_args()
    report = generate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"assets={report['assets']} average={report['summary']['average_net_return_pct']} output={args.output}")
    return 0 if report["assets"] >= 20 else 1


if __name__ == "__main__":
    raise SystemExit(main())
