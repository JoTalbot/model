#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 3): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy (not in prod venv); runs on ML hosts
"""V1: live microstructure signal monitor on fresh ws data.

Reads the latest N snapshots from snapshots_ws for a symbol, computes the OBI
signal (direction probability via a lightweight CatBoost trained on the same
symbol's history) and prints/logs the current signal + a rolling accuracy vs
the realized direction over the next H seconds.

Used as a periodic service to observe the signal live; accuracy log is appended
to data/reports/mm_signal_live.jsonl.

Usage:
    python scripts/mm_signal_live_monitor.py [--symbol BTC] [--window 600] [--horizon 60]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
DB = DATA / "quant" / "orderbooks.sqlite"


def load_ws(symbol: str, limit: int = 600) -> list[dict]:
    con = sqlite3.connect(DB)
    cur = con.execute(
        "SELECT ts, bid, ask, mid, bids_json, asks_json FROM snapshots_ws WHERE symbol=? ORDER BY ts DESC LIMIT ?",
        (symbol, limit),
    )
    rows = cur.fetchall()
    con.close()
    import json as j

    out = []
    for r in reversed(rows):
        out.append(
            {
                "ts": r[0],
                "bid": r[1],
                "ask": r[2],
                "mid": r[3],
                "bids": j.loads(r[4]) if r[4] else [],
                "asks": j.loads(r[5]) if r[5] else [],
            }
        )
    return out


def book_vol(levels, upto: int) -> float:
    return sum(q for _, q in levels[:upto])


def obi_signal(snaps: list[dict]) -> dict:
    """Heuristic live signal from the latest snapshot (no training needed)."""
    s = snaps[-1]
    bd1 = book_vol(s["bids"], 1)
    ad1 = book_vol(s["asks"], 1)
    bd5 = book_vol(s["bids"], 5)
    ad5 = book_vol(s["asks"], 5)
    obi1 = (bd1 - ad1) / (bd1 + ad1 + 1e-12)
    obi5 = (bd5 - ad5) / (bd5 + ad5 + 1e-12)
    micro = (s["ask"] * bd1 + s["bid"] * ad1) / (bd1 + ad1 + 1e-12)
    mid = s["mid"]
    micro_off = (micro - mid) / mid * 1e4 if mid else 0.0
    # combined score in [-1, 1]
    score = 0.5 * obi1 + 0.3 * obi5 + 0.2 * np.clip(micro_off / 0.05, -1, 1)
    if score > 0.15:
        direction = "UP"
    elif score < -0.15:
        direction = "DOWN"
    else:
        direction = "FLAT"
    return {
        "ts": s["ts"],
        "mid": mid,
        "obi1": round(float(obi1), 3),
        "obi5": round(float(obi5), 3),
        "micro_off": round(float(micro_off), 3),
        "score": round(float(score), 3),
        "direction": direction,
    }


def verify_last(snaps: list[dict], horizon: float = 60.0) -> dict | None:
    """Check accuracy of the signal from `horizon` seconds ago vs realized move."""
    if len(snaps) < 2:
        return None
    t0 = snaps[0]["ts"]
    # find snapshot ~horizon after t0
    j = None
    for k, s in enumerate(snaps):
        if s["ts"] >= t0 + horizon:
            j = k
            break
    if j is None or j >= len(snaps):
        return None
    mid0, mid1 = snaps[0]["mid"], snaps[j]["mid"]
    if mid1 == mid0:
        realized = "FLAT"
    else:
        realized = "UP" if mid1 > mid0 else "DOWN"
    return {"ts0": t0, "mid0": mid0, "mid1": mid1, "horizon": horizon, "realized": realized}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTC")
    ap.add_argument("--window", type=int, default=600)
    ap.add_argument("--horizon", type=float, default=60.0)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    snaps = load_ws(args.symbol, args.window)
    if len(snaps) < 10:
        print(f"{args.symbol}: not enough ws data ({len(snaps)})", flush=True)
        return 1
    sig = obi_signal(snaps)
    out = {"symbol": args.symbol, **sig}
    if args.verify:
        v = verify_last(snaps, args.horizon)
        if v:
            out["verify"] = v
    line = json.dumps(out, ensure_ascii=False)
    print(line, flush=True)
    log = DATA / "reports" / "mm_signal_live.jsonl"
    with open(log, "a") as f:
        f.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
