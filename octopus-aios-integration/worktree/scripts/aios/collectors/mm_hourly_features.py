#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 3): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy (not in prod venv); runs on ML hosts
"""Hourly microstructure features from the ws stream (Edge Lab 2026-08-17).

Aggregates snapshots_ws (1Hz depth, 19 symbols) and trades_ws (5s taker
buckets) into per-symbol hourly features:
  obi1_mean/std, depth_imb_mean, taker_buy_frac, spread_mean_bps,
  mid_ret, mid_vol (std of 1s returns), n_snapshots.
This is the "external data" the directional ML does not see: order flow and
depth dynamics at the 1h scale.

Preliminary status: the ws stream holds ~40h (started 2026-08-15); honest ML
needs weeks. The pipeline runs weekly via aios-mm-hourly-features.timer and
appends history to data/reports/mm_hourly_features.jsonl.

Read-only.

Usage:
    python scripts/mm_hourly_features.py [--db data/quant/orderbooks.sqlite]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
DB = DATA / "quant" / "orderbooks.sqlite"
OUT = DATA / "reports" / "mm_hourly_features.jsonl"


def hour_bucket(ts: float) -> int:
    return int(ts) // 3600


def aggregate_hour(snaps: list[tuple], trades: list[tuple]) -> dict:
    """Pure aggregation of one symbol-hour (unit-tested)."""

    mids = np.array([r[2] for r in snaps], dtype=float)
    obi1 = []
    depth_imb = []
    spread = []
    for r in snaps:
        bid, ask, mid = r[0], r[1], r[2]
        bd = r[3]
        ad = r[4]
        obi1.append((bd - ad) / (bd + ad + 1e-12))
        depth_imb.append(bd / (bd + ad + 1e-12))
        spread.append((ask - bid) / mid * 1e4 if mid else 0.0)
    buy = sum(t[1] for t in trades)
    sell = sum(t[2] for t in trades)
    total = buy + sell
    rets = np.diff(mids) / mids[:-1] if len(mids) > 1 else np.array([0.0])
    return {
        "n_snapshots": len(snaps),
        "n_trade_buckets": len(trades),
        "obi1_mean": round(float(np.mean(obi1)), 4) if obi1 else None,
        "obi1_std": round(float(np.std(obi1)), 4) if obi1 else None,
        "depth_imb_mean": round(float(np.mean(depth_imb)), 4) if depth_imb else None,
        "taker_buy_frac": round(buy / total, 4) if total > 0 else None,
        "spread_mean_bps": round(float(np.mean(spread)), 3) if spread else None,
        "mid_ret": round(float(mids[-1] / mids[0] - 1.0) * 1e4, 2) if len(mids) > 1 else 0.0,
        "mid_vol_bps": round(float(np.std(rets)) * 1e4, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not args.db.exists():
        print("SKIP: db not found")
        return 0
    con = sqlite3.connect(args.db, timeout=30)
    symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM snapshots_ws ORDER BY symbol")]
    rows = []
    for sym in symbols:
        snaps = con.execute(
            "SELECT bid, ask, mid, bid_depth_usd, ask_depth_usd, ts FROM snapshots_ws WHERE symbol=? ORDER BY ts",
            (sym,),
        ).fetchall()
        trades = con.execute(
            "SELECT ts, buy_vol, sell_vol FROM trades_ws WHERE symbol=? ORDER BY ts", (sym,)
        ).fetchall()
        if not snaps:
            continue
        # group by hour bucket
        from collections import defaultdict

        sb = defaultdict(list)
        for r in snaps:
            sb[hour_bucket(r[5])].append(r[:5])
        tb = defaultdict(list)
        for r in trades:
            tb[hour_bucket(r[0])].append(r)
        for h in sorted(sb):
            if len(sb[h]) < 300:  # час с дырами не считаем
                continue
            feat = aggregate_hour(sb[h], tb.get(h, []))
            feat["symbol"] = sym
            feat["hour"] = h
            feat["hour_utc"] = datetime.fromtimestamp(h * 3600, tz=UTC).isoformat()
            rows.append(feat)
    con.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as fh:
        for r in sorted(rows, key=lambda x: (x["symbol"], x["hour"])):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"appended {len(rows)} symbol-hours -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
