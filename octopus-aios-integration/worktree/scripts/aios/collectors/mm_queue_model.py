#!/usr/bin/env python3
"""Empirical queue/execution model for market making from the ws dataset.

Reads snapshots_ws (1Hz depth) and trades_ws (5s taker-volume buckets) and
estimates, per symbol:
- touch lifetime (how long the best bid/ask price stays unchanged);
- volume traded against a touch until it dies;
- fill probability for a maker order joining the BACK of the queue with size
  Q USD and a horizon of tau seconds:
      P(fill) = P(cumulative taker volume against the touch within tau
                  >= level_size_at_join + our_size)

Conservative assumptions (documented): joining the back of the queue means all
resting size S trades before our order; we never re-queue; a touch event whose
price changed inside a 5s trade bucket is dropped (volume attribution ambiguous).

Read-only research; never trades.

Usage:
    python scripts/mm_queue_model.py [--symbols BTC,ETH,SOL,BNB,NEAR,ADA,LINK,XRP]
        [--out data/reports/mm_queue_model.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
DB = DATA / "quant" / "orderbooks.sqlite"
TAUS = [5, 10, 30, 60]
QUOTE_USD = [100, 500, 2000]


# ------------------------------------------------------------- pure helpers --
def extract_touch_events(snaps: list[dict], side: str) -> list[dict]:
    """Split a 1Hz snapshot stream into touch events (consecutive same best px)."""

    px_key = "bid" if side == "bid" else "ask"
    lvl_idx = 0
    events: list[dict] = []
    i = 0
    n = len(snaps)
    while i < n:
        j = i
        while j + 1 < n and snaps[j + 1][px_key] == snaps[i][px_key]:
            j += 1
        s0 = snaps[i]
        levels = s0["bids"] if side == "bid" else s0["asks"]
        size = float(levels[lvl_idx][1]) if levels else 0.0
        events.append(
            {
                "side": side,
                "px": s0[px_key],
                "start_ts": s0["ts"],
                "end_ts": snaps[j]["ts"],
                "size_at_join": size,
                "mid": s0["mid"],
            }
        )
        i = j + 1
    return events


def assign_buckets(snaps: list[dict], events: list[dict], buckets: list[dict], side: str) -> list[dict]:
    """Attach 5s trade buckets to touch events (bid<-sell_vol, ask<-buy_vol).

    A bucket [T-5, T] belongs to a touch event when the touch price at both
    ends of the bucket equals the event price; otherwise it is dropped as
    ambiguous. Returns events with 'cum': sorted [(dt_s, cum_vol)].
    """

    import bisect

    px_key = "bid" if side == "bid" else "ask"
    vol_key = "sell" if side == "bid" else "buy"
    times = [s["ts"] for s in snaps]

    def px_at(t: float) -> float | None:
        j = bisect.bisect_right(times, t) - 1
        return snaps[j][px_key] if j >= 0 else None

    # price -> sorted (start_ts, event); buckets attach to the last event
    # starting at or before the bucket start
    by_price: dict[float, list[tuple[float, dict]]] = {}
    for e in events:
        by_price.setdefault(e["px"], []).append((e["start_ts"], e))
    for grp in by_price.values():
        grp.sort(key=lambda t: t[0])

    starts_by_price = {px: [g[0] for g in grp] for px, grp in by_price.items()}
    pts_by_event: dict[int, list[tuple[float, float]]] = {id(e): [] for e in events}
    for b in buckets:
        t_start = b["ts"] - 5.0
        p0 = px_at(t_start)
        p1 = px_at(b["ts"])
        if p0 is None or p0 != p1:
            continue  # touch changed inside the bucket -> ambiguous
        grp = by_price.get(p0)
        if not grp:
            continue
        j = bisect.bisect_right(starts_by_price[p0], t_start) - 1
        if j < 0:
            continue
        e = grp[j][1]
        pts_by_event[id(e)].append((t_start, b[vol_key]))

    out = []
    for e in events:
        cum = []
        acc = 0.0
        for t_start, vol in sorted(pts_by_event[id(e)]):
            acc += vol
            cum.append((t_start - e["start_ts"], acc))
        e["cum"] = cum
        out.append(e)
    return out


def touch_stats(events: list[dict]) -> dict:
    if not events:
        return {}
    lifetimes = sorted(e["end_ts"] - e["start_ts"] + 1.0 for e in events)
    deaths = sorted(sum(v for _, v in e["cum"]) for e in events)
    sizes = sorted(e["size_at_join"] for e in events)
    return {
        "n_events": len(events),
        "lifetime_median_s": round(statistics.median(lifetimes), 1),
        "lifetime_p90_s": round(lifetimes[int(len(lifetimes) * 0.9)], 1),
        "v_death_median": round(statistics.median(deaths), 2),
        "v_death_p90": round(deaths[int(len(deaths) * 0.9)], 2),
        "size_median": round(statistics.median(sizes), 4),
    }


def fill_prob(events: list[dict], tau: float, q_base: float, min_n: int = 30) -> float | None:
    """P(cumulative volume against the touch within tau >= size_at_join + q)."""

    alive = [e for e in events if e["end_ts"] - e["start_ts"] + 1.0 >= tau]
    if len(alive) < min_n:
        return None
    filled = 0
    for e in alive:
        v = 0.0
        for dt, acc in e["cum"]:
            if dt <= tau:
                v = acc
            else:
                break
        if v >= e["size_at_join"] + q_base:
            filled += 1
    return round(filled / len(alive), 4)


# ------------------------------------------------------------------- loader --
def load_snaps(symbol: str, min_interval: float = 0.9) -> list[dict]:
    con = sqlite3.connect(DB, timeout=30)
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


def load_buckets(symbol: str) -> list[dict]:
    con = sqlite3.connect(DB, timeout=30)
    cur = con.execute("SELECT ts, buy_vol, sell_vol FROM trades_ws WHERE symbol=? ORDER BY ts", (symbol,))
    out = [{"ts": r[0], "buy": r[1], "sell": r[2]} for r in cur]
    con.close()
    return out


# ---------------------------------------------------------------------- main --
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="BTC,ETH,SOL,BNB,NEAR,ADA,LINK,XRP")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "reports" / "mm_queue_model.json")
    args = ap.parse_args()

    report: dict[str, dict] = {}
    for symbol in args.symbols.split(","):
        symbol = symbol.strip()
        snaps = load_snaps(symbol)
        buckets = load_buckets(symbol)
        if len(snaps) < 1000 or len(buckets) < 100:
            print(f"{symbol}: мало данных (snaps={len(snaps)} buckets={len(buckets)})", flush=True)
            continue
        row: dict[str, object] = {"snapshots": len(snaps), "buckets": len(buckets)}
        for side in ("bid", "ask"):
            events = extract_touch_events(snaps, side)
            events = assign_buckets(snaps, events, buckets, side)
            st = touch_stats(events)
            row[side] = st
            fills: dict[str, object] = {}
            for tau in TAUS:
                for q in QUOTE_USD:
                    med_mid = statistics.median(e["mid"] for e in events)
                    q_base = q / med_mid if med_mid else 0.0
                    fp = fill_prob(events, float(tau), q_base)
                    fills[f"tau{tau}s_q${q}"] = fp
            row[side + "_fill"] = fills
        report[symbol] = row
        print(
            f"{symbol}: bid n={row['bid'].get('n_events')} life_med={row['bid'].get('lifetime_median_s')}s "
            f"ask n={row['ask'].get('n_events')} life_med={row['ask'].get('lifetime_median_s')}s",
            flush=True,
        )
        for side in ("bid", "ask"):
            f = row[side + "_fill"]
            line = (
                "  "
                + side
                + ": "
                + " ".join(f"τ{t}s/Q${q}={f[f'tau{t}s_q${q}']}" for t in TAUS for q in (100, 500, 2000))
            )
            print(line, flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"report -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
