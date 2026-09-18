#!/usr/bin/env python3
"""Hourly derivatives accumulator: appends current LSR/OI/taker-buy-ratio.

Binance Futures API caps history at ~500 records; to build longer history we
append current values periodically. Files (append-only jsonl):
  data/derivatives/history/{symbol}_global_lsr.jsonl
  data/derivatives/history/{symbol}_top_lsr.jsonl
  data/derivatives/history/{symbol}_oi.jsonl
  data/derivatives/history/{symbol}_taker.jsonl
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

FAPI = "https://fapi.binance.com"
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
OUT = DATA / "derivatives" / "history"
SYMBOLS = ["BTC", "ETH", "SOL"]


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for sym in SYMBOLS:
        now = time.time()
        try:
            lsr = get(f"{FAPI}/futures/data/globalLongShortAccountRatio?symbol={sym}USDT&period=1h&limit=1")[0]
            top = get(f"{FAPI}/futures/data/topLongShortAccountRatio?symbol={sym}USDT&period=1h&limit=1")[0]
            oi = get(f"{FAPI}/futures/data/openInterestHist?symbol={sym}USDT&period=1h&limit=1")[0]
            k = get(f"{FAPI}/fapi/v1/klines?symbol={sym}USDT&interval=1h&limit=1")[0]
            vol, taker = float(k[5]), float(k[9])
            rows = {
                f"{sym}_global_lsr": {"ts": now, "lsr": float(lsr["longShortRatio"])},
                f"{sym}_top_lsr": {"ts": now, "lsr": float(top["longShortRatio"])},
                f"{sym}_oi": {"ts": now, "oi": float(oi["sumOpenInterest"])},
                f"{sym}_taker": {"ts": now, "taker_buy_ratio": taker / vol if vol else 0.5},
            }
            for name, row in rows.items():
                with open(OUT / f"{name}.jsonl", "a") as f:
                    f.write(json.dumps(row) + "\n")
        except Exception as e:
            print(f"{sym}: {e}", flush=True)
        time.sleep(0.2)
    print("done", flush=True)


if __name__ == "__main__":
    main()
