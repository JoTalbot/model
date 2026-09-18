#!/usr/bin/env python3
"""V6: daily funding/OI collector (append-only history).

Binance Futures public endpoints; appends today's funding rate and OI snapshot
for the 33-symbol universe into data/quant/funding_oi/daily_{symbol}.jsonl
and open_interest_{symbol}.jsonl. Designed to run daily via systemd timer so the
OI history grows from today (funding history is deep already, OI is not).

Usage:
    python scripts/collect_funding_oi_daily.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
OUT = DATA / "quant" / "funding_oi"
SYMBOLS = [
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "BNB",
    "DOGE",
    "ADA",
    "LINK",
    "AVAX",
    "UNI",
    "NEAR",
    "LTC",
    "DOT",
    "SUI",
    "APT",
    "ARB",
    "OP",
    "INJ",
    "TIA",
    "SEI",
    "FET",
    "BONK",
    "PEPE",
    "SHIB",
    "TRX",
    "TON",
    "ETC",
    "FIL",
    "ATOM",
    "KAS",
    "WIF",
    "RENDER",
    "POL",
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    n_ok = 0
    for sym in SYMBOLS:
        try:
            fr = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}USDT&limit=1")
            oi = get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}USDT")
            with open(OUT / f"daily_{sym}.jsonl", "a") as f:
                f.write(
                    json.dumps(
                        {
                            "date": today,
                            "funding_rate": float(fr[0]["fundingRate"]),
                            "funding_time": int(fr[0]["fundingTime"]),
                        }
                    )
                    + "\n"
                )
            with open(OUT / f"open_interest_{sym}.jsonl", "a") as f:
                f.write(json.dumps({"date": today, "oi": float(oi["openInterest"]), "time": int(oi["time"])}) + "\n")
            n_ok += 1
        except Exception as e:
            print(f"{sym} FAIL {e}", flush=True)
        time.sleep(0.12)
    print(f"done {n_ok}/{len(SYMBOLS)} symbols", flush=True)


if __name__ == "__main__":
    main()
