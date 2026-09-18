#!/usr/bin/env python3
"""Priority-queue fill calibration on the FULL 100ms BTC/ETH stream.

Joining at the moment a new touch price appears means our order rests at the
FRONT of the new level (size ahead of us is minimal). Reuses the touch/bucket
machinery of scripts/mm_queue_model.py but at 100ms resolution, so S0 (size at
the first snapshot of a new touch) is measured much more precisely and tau
grids can be sub-second.

Preliminary: the full stream has only been collected since 2026-08-17 10:44 UTC
(~9h at first run); run weekly via aios-mm-queue-priority.timer.

Read-only research; never trades.

Usage:
    python scripts/mm_queue_priority.py [--symbols BTC,ETH]
        [--out data/reports/mm_queue_priority.json]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.aios.collectors.mm_queue_model import (
    assign_buckets,
    extract_touch_events,
    fill_prob,
    load_buckets,
    touch_stats,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))


TAUS = [1.0, 2.0, 5.0, 10.0, 30.0]
QUOTE_USD = [100, 500, 2000]


def load_snaps_full(symbol: str, min_interval: float = 0.1) -> list[dict]:
    """100ms-resolution snapshot loader (same shape as mm_queue_model loader)."""

    import sqlite3

    con = sqlite3.connect(DATA / "quant" / "orderbooks.sqlite", timeout=30)
    cur = con.execute(
        "SELECT ts, bid, ask, mid, bids_json, asks_json FROM snapshots_ws WHERE symbol=? ORDER BY ts", (symbol,)
    )
    out: list[dict] = []
    last = -1e18
    for r in cur:
        if r[0] - last < min_interval:
            continue
        last = r[0]
        out.append(
            {
                "ts": r[0],
                "bid": r[1],
                "ask": r[2],
                "mid": r[3],
                "bids": json.loads(r[4]) if r[4] else [],
                "asks": json.loads(r[5]) if r[5] else [],
            }
        )
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="BTC,ETH")
    ap.add_argument("--out", type=Path, default=DATA / "reports" / "mm_queue_priority.json")
    args = ap.parse_args()

    report: dict[str, dict] = {}
    for symbol in args.symbols.split(","):
        symbol = symbol.strip()
        snaps = load_snaps_full(symbol)
        buckets = load_buckets(symbol)
        if len(snaps) < 1000 or len(buckets) < 50:
            print(f"{symbol}: мало данных (snaps={len(snaps)} buckets={len(buckets)})", flush=True)
            continue
        row: dict[str, object] = {
            "snapshots_100ms": len(snaps),
            "span_h": round((snaps[-1]["ts"] - snaps[0]["ts"]) / 3600, 1),
        }
        for side in ("bid", "ask"):
            events = extract_touch_events(snaps, side)
            events = assign_buckets(snaps, events, buckets, side)
            st = touch_stats(events)
            row[side] = st
            fills: dict[str, object] = {}
            med_mid = sorted(e["mid"] for e in events)[len(events) // 2] if events else 1.0
            for tau in TAUS:
                for q in QUOTE_USD:
                    fp = fill_prob(events, tau, q / med_mid, min_n=20)
                    fills[f"tau{tau}s_q${q}"] = fp
            row[side + "_fill"] = fills
        report[symbol] = row
        print(
            f"{symbol}: {row['snapshots_100ms']} snaps {row['span_h']}h "
            f"bid_life={row['bid'].get('lifetime_median_s')}s ask_life={row['ask'].get('lifetime_median_s')}s",
            flush=True,
        )
        for side in ("bid", "ask"):
            f = row[side + "_fill"]
            print(
                "  "
                + side
                + ": "
                + " ".join(f"τ{t}s/Q${q}={f[f'tau{t}s_q${q}']}" for t in TAUS for q in (100, 500, 2000)),
                flush=True,
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"report -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
