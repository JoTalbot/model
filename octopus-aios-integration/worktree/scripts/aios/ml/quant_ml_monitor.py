#!/usr/bin/env python3
"""ML drift & freshness monitor for the quant signal pipeline.

Reads ml_signals.json and the underlying CSVs, tracks the prob_up
distribution history, flags stale data or a degenerate (collapsed)
distribution. Read-only; appends one history entry per run.

Usage:
    python scripts/quant_ml_monitor.py [--history data/reports/quant_ml_monitor_history.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_DIR = REPO_ROOT / "data" / "quant"
SIGNALS = QUANT_DIR / "ml_signals.json"
HISTORY = REPO_ROOT / "data" / "reports" / "quant_ml_monitor_history.json"
OUT = REPO_ROOT / "data" / "reports" / "quant_ml_monitor.json"

MAX_SIGNAL_AGE_H = 3.0
MAX_DATA_AGE_H = 4.0
MIN_PROB_SPREAD = 0.05  # below this -> suspiciously constant distribution
CALIBRATION = QUANT_DIR / "ml_prob_calibration.json"
V2_MODEL = QUANT_DIR / "models" / "catboost_price_dir_v2.cbm"
PORTFOLIOS = (
    REPO_ROOT / "data" / "multi_exchange_portfolios_owner_paper.json",
    REPO_ROOT / "data" / "multi_exchange_portfolios_owner_paper_control.json",
)
MAX_AB_ZERO_TRADE_DAYS = 3.0  # A/B paper: alert when enabled but no trades this long


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=HISTORY)
    args = parser.parse_args()

    now = time.time()
    problems: list[str] = []

    # 1) Signals file freshness + distribution.
    if not SIGNALS.exists():
        problems.append(f"ml_signals.json not found: {SIGNALS}")
        print(json.dumps({"status": "ERROR", "problems": problems}, ensure_ascii=False, indent=2))
        return 1
    sig_age_h = (now - SIGNALS.stat().st_mtime) / 3600
    payload = json.loads(SIGNALS.read_text(encoding="utf-8"))
    sigs = [s for s in payload.get("signals", []) if s.get("ok") and isinstance(s.get("prob_up"), (int, float))]
    if sig_age_h > MAX_SIGNAL_AGE_H:
        problems.append(f"ml_signals.json stale: {sig_age_h:.1f}h > {MAX_SIGNAL_AGE_H}h")
    probs = [float(s["prob_up"]) for s in sigs]

    # 2) Underlying CSV freshness (median of newest bar age).
    data_ages = []
    for f in glob.glob(str(QUANT_DIR / "*" / "binance" / "*_1h.csv")):
        try:
            with open(f) as fh:
                lines = fh.readlines()
            last_ts = int(lines[-1].split(",")[0])
            data_ages.append((now - last_ts / 1000) / 3600)
        except (OSError, ValueError, IndexError):
            continue
    if data_ages:
        median_age = statistics.median(data_ages)
        if median_age > MAX_DATA_AGE_H:
            problems.append(f"median CSV age {median_age:.1f}h > {MAX_DATA_AGE_H}h")
    else:
        median_age = None
        problems.append("no CSV data found")

    # 3) Distribution stats.
    spread = max(probs) - min(probs) if probs else 0.0
    n_ge_060 = sum(1 for p in probs if p >= 0.60)
    n_ge_065 = sum(1 for p in probs if p >= 0.65)
    if probs and spread < MIN_PROB_SPREAD:
        problems.append(f"prob_up degenerate: spread={spread:.4f} < {MIN_PROB_SPREAD}")

    # 3b) Calibration freshness: model file must never be newer than the
    #     calibration derived from its own distribution.
    cal_stale = False
    if CALIBRATION.exists() and V2_MODEL.exists():
        cal_age = now - CALIBRATION.stat().st_mtime
        model_age = now - V2_MODEL.stat().st_mtime
        if model_age < cal_age - 60:  # model touched after calibration -> stale
            problems.append("ml_prob_calibration stale: model newer than calibration")
            cal_stale = True
    elif V2_MODEL.exists():
        problems.append("ml_prob_calibration missing while v2 model deployed")
        cal_stale = True

    # 3c) A/B paper stall: entry_mode enabled but zero closed trades for days.
    ab_info = {"main_trades": None, "control_trades": None, "days_running": None}
    for path in PORTFOLIOS:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        exchanges = [v for k, v in data.items() if k not in {"cross_arbitrage", "_risk_state"}]
        trades = sum(int(v.get("closed_trades", 0) or 0) for v in exchanges)
        risk = data.get("_risk_state") or {}
        days = (now - float(risk.get("started_at", now))) / 86400.0
        enabled = (risk.get("entry_mode") or "").lower() == "enabled"
        tag = "main" if "control" not in path.name else "control"
        ab_info[tag + "_trades"] = trades
        ab_info["days_running"] = round(days, 1)
        if enabled and trades == 0 and days > MAX_AB_ZERO_TRADE_DAYS:
            problems.append(
                f"Directional v2 paper ({tag}): 0 входов за {days:.1f} дн при entry_mode=enabled"
            )

    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "n_signals": len(probs),
        "prob_mean": round(statistics.mean(probs), 4) if probs else None,
        "prob_median": round(statistics.median(probs), 4) if probs else None,
        "prob_min": round(min(probs), 4) if probs else None,
        "prob_max": round(max(probs), 4) if probs else None,
        "prob_spread": round(spread, 4),
        "n_ge_060": n_ge_060,
        "n_ge_065": n_ge_065,
        "signal_age_h": round(sig_age_h, 2),
        "median_csv_age_h": round(median_age, 2) if median_age is not None else None,
        "model": payload.get("model_available"),
        "generated_at": payload.get("generated_at"),
        "calibration_stale": cal_stale,
        "ab_zero_trade_days": ab_info,
    }

    # 4) Compare with previous snapshot (drift = big shift in mean).
    history = []
    if args.history.exists():
        try:
            history = json.loads(args.history.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            history = []
    drift = None
    if history and entry["prob_mean"] is not None and history[-1].get("prob_mean") is not None:
        delta = entry["prob_mean"] - history[-1]["prob_mean"]
        if abs(delta) > 0.10:
            drift = round(delta, 4)
            problems.append(f"prob_mean drift vs prev: {delta:+.4f}")
    history.append(entry)
    history = history[-200:]
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(json.dumps(history, indent=2, ensure_ascii=False))

    report = {
        "status": "WARN" if problems else "OK",
        "problems": problems,
        "current": entry,
        "prev_mean": history[-2]["prob_mean"] if len(history) >= 2 else None,
        "drift_vs_prev": drift,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
