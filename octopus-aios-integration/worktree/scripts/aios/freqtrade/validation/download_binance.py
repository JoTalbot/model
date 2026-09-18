#!/usr/bin/env python3
"""Download daily Binance klines into freqtrade JSON format (no API keys).

Freqtrade's download-data refuses to run without exchange credentials, so we
fetch via the public klines REST API (same transport as run_t2_momentum.py).

Output: <datadir>/<SYM>_USDT-1d.json  (freqtrade JSON: [ts, o, h, l, c, v])

Usage:
    python download_binance.py --datadir /opt/octopus/data/freqtrade/data \
        --symbols BTC,ETH,SOL,BNB,NEAR --start 2019-01-01
"""

import argparse
import json
import time
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
LIMIT = 1000  # Binance klines max per request


def fetch_klines(symbol: str, start_ms: int, transport=None) -> list[list]:
    t = transport or _default_transport
    out: list[list] = []
    cur = start_ms
    while True:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1d&startTime={cur}&limit={LIMIT}"
        raw = t(url)
        batch = json.loads(raw.decode())
        if not batch:
            break
        out.extend(batch)
        cur = batch[-1][0] + 1
        if len(batch) < LIMIT:
            break
        time.sleep(0.3)
    return out


def to_freqtrade(klines: list[list]) -> list[list]:
    rows = []
    for k in klines:
        o, h, lo, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        v = float(k[5])
        rows.append([int(k[0]), o, h, lo, c, v])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datadir", required=True)
    ap.add_argument("--symbols", default="BTC,ETH,SOL,BNB,NEAR")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--transport", help="injectable transport (tests)")
    a = ap.parse_args()
    out_dir = Path(a.datadir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start_ms = int(time.mktime(time.strptime(a.start, "%Y-%m-%d"))) * 1000
    for sym in a.symbols.split(","):
        klines = fetch_klines(sym, start_ms, transport=a.transport)
        rows = to_freqtrade(klines)
        p = out_dir / f"{sym}_USDT-1d.json"
        p.write_text(json.dumps(rows))
        first = time.strftime("%Y-%m-%d", time.gmtime(rows[0][0] / 1000))
        last = time.strftime("%Y-%m-%d", time.gmtime(rows[-1][0] / 1000))
        print(f"{sym}: {len(rows)} bars  {first} -> {last}")
    return 0


def _default_transport(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


if __name__ == "__main__":
    raise SystemExit(main())
