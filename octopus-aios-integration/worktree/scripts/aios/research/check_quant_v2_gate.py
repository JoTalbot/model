#!/usr/bin/env python3
"""Evaluate Directional-v2 paper/backtest gates; never places orders."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any


def evaluate_gate(backtest: dict[str, Any], portfolio: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    rows = list(backtest.get("results") or [])
    ml_returns = [float(row.get("net_return_pct", row.get("ml_pct", 0.0)) or 0.0) for row in rows]
    positive_ratio = (sum(value > 0 for value in ml_returns) / len(ml_returns)) if ml_returns else 0.0
    average_return = statistics.mean(ml_returns) if ml_returns else 0.0

    exchanges = [value for key, value in portfolio.items() if key not in {"cross_arbitrage", "_risk_state"}]
    closed = sum(int(value.get("closed_trades", 0) or 0) for value in exchanges)
    realized = sum(float(value.get("realized_pnl_usd", 0.0) or 0.0) for value in exchanges)
    net_profit = sum(float(value.get("net_profit_usd", 0.0) or 0.0) for value in exchanges)
    net_loss = sum(float(value.get("net_loss_usd", 0.0) or 0.0) for value in exchanges)
    profit_factor = (net_profit / net_loss) if net_loss > 0 else (float("inf") if net_profit > 0 else 0.0)
    risk = portfolio.get("_risk_state") or {}
    started_value = risk.get("started_at")
    started_at = float(started_value) if started_value is not None else now
    paper_days = max(0.0, (now - started_at) / 86_400.0)
    max_drawdown = float(risk.get("max_drawdown_pct_seen", 0.0) or 0.0)
    unpriced = int(risk.get("unpriced_positions", 0) or 0)

    checks = {
        "cost_model_v2": backtest.get("cost_model") == "directional_v2",
        "walk_forward": backtest.get("walk_forward") is True,
        "backtest_assets_20": len(rows) >= 20,
        "backtest_average_positive": average_return > 0.0,
        "backtest_positive_ratio_50pct": positive_ratio >= 0.50,
        "paper_days_30": paper_days >= 30.0,
        "closed_trades_200": closed >= 200,
        "realized_pnl_positive": realized > 0.0,
        "profit_factor_1_2": profit_factor >= 1.20,
        "max_drawdown_3pct": max_drawdown <= 3.0,
        "no_unpriced_positions": unpriced == 0,
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "metrics": {
            "backtest_assets": len(rows),
            "backtest_average_return_pct": round(average_return, 6),
            "backtest_positive_ratio": round(positive_ratio, 6),
            "paper_days": round(paper_days, 3),
            "closed_trades": closed,
            "realized_pnl_usd": round(realized, 8),
            "profit_factor": round(profit_factor, 6) if profit_factor != float("inf") else "inf",
            "max_drawdown_pct": round(max_drawdown, 6),
            "unpriced_positions": unpriced,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest", type=Path, default=Path("data/reports/backtest_directional_v2.json"))
    parser.add_argument("--portfolio", type=Path, default=Path("data/multi_exchange_portfolios_v2.json"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate_gate(
            json.loads(args.backtest.read_text(encoding="utf-8")),
            json.loads(args.portfolio.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError) as exc:
        result = {"ready": False, "checks": {"input_available": False}, "error": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        failed = [name for name, passed in result.get("checks", {}).items() if not passed]
        print(f"ready={result.get('ready', False)} failed={','.join(failed) or 'none'}")
        if result.get("metrics"):
            print(json.dumps(result["metrics"], ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
