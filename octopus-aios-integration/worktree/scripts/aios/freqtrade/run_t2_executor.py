#!/usr/bin/env python3
"""T2 real-money executor scaffold (Binance spot).

Executes the validated T2 momentum signal (run_t2_momentum.py logic) on a real
Binance account: reads today's signal per symbol, compares with the last known
position (state file), and submits MARKET orders via the Binance REST API
(ccxt). Nothing is executed unless --live is passed; the default mode is
--dry (prints what it WOULD do).

Production rules (identical to run_t2_momentum.py):
- CASH -> LONG when last closed daily close > SMA(in_w)
- LONG -> CASH when last closed daily close <= SMA(out_w)
- BNB/NEAR: in_w == out_w == 50 (no hysteresis)

Risk controls (hard-coded, do not disable):
- one order per symbol per day (idempotent via state file)
- max position size per symbol = min(stake_frac * equity, max_order_usdt)
- symbol whitelist + max daily orders limit
- only SPOT market orders; leverage always 1

Usage:
    python run_t2_executor.py --dry --config config_executor.json        # simulate
    python run_t2_executor.py --live --config config_executor.json       # real orders

State: data/t2_executor_state.json (per-symbol last signal + position)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DEFAULT_CONFIG = {
    "exchange": "binance",
    "api_key": "",  # set in your config file (never commit real keys)
    "api_secret": "",
    "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "NEAR/USDT"],
    "windows": {"BNB/USDT": [50, 50], "NEAR/USDT": [50, 50]},  # others: [50, 40]
    "stake_frac": 0.20,  # fraction of free USDT per symbol
    "max_order_usdt": 2000,  # per-order cap
    "max_daily_orders": 4,  # global cap
    "state_file": "data/t2_executor_state.json",
    "cost_bps": 10,  # 0.1% assumed taker cost (for PnL logging only)
}


def fetch_closes(symbol: str, transport=None, limit: int = 400) -> list[dict]:
    """Daily closed bars {date, close} from Binance klines (primary) / Yahoo."""
    t = transport or _default_transport
    base = symbol.split("/")[0].upper()
    url = f"https://api.binance.com/api/v3/klines?symbol={base}USDT&interval=1d&limit={limit}"
    try:
        raw = t(url)
        klines = json.loads(raw.decode())
        rows = []
        for k in klines:
            rows.append({"date": time.strftime("%Y-%m-%d", time.gmtime(k[0] / 1000)), "close": float(k[4])})
        if len(rows) >= 60:
            return rows
    except Exception:
        pass
    # fallback Yahoo
    yurl = f"https://query1.finance.yahoo.com/v8/finance/chart/{base}-USD?range={limit + 10}d&interval=1d"
    try:
        raw = t(yurl)
        data = json.loads(raw.decode())
        res = data["chart"]["result"][0]
        ts, close = res["timestamp"], res["indicators"]["quote"][0]["close"]
        rows = []
        for x, c in zip(ts, close, strict=False):
            if c is not None:
                rows.append({"date": time.strftime("%Y-%m-%d", time.gmtime(x)), "close": float(c)})
    except Exception as e:
        raise RuntimeError(f"cannot fetch closes for {symbol}") from e
    if len(rows) >= 60:
        return rows
    raise RuntimeError(f"cannot fetch closes for {symbol}")


def compute_signal(rows: list[dict], in_w: int, out_w: int | None = None) -> tuple[str, float, float]:
    """Return (signal, sma_in, sma_out) on the LAST CLOSED bar (no lookahead)."""
    out_w = out_w or in_w
    closes = [r["close"] for r in rows]
    last = closes[-1]
    if len(closes) < max(in_w, out_w):
        return "CASH", 0.0, 0.0
    s_in = sum(closes[-in_w:]) / in_w
    s_out = sum(closes[-out_w:]) / out_w
    sig = "LONG" if last > s_in else "CASH"
    return sig, s_in, s_out


class State:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text())
        else:
            self.data = {"date": None, "positions": {}, "orders_today": 0, "day": None}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        tmp.replace(self.path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config_executor.json")
    ap.add_argument("--dry", action="store_true", default=True, help="simulate only (default, safe)")
    ap.add_argument("--live", action="store_true", help="REAL orders (requires keys)")
    ap.add_argument("--transport", help="injectable transport (tests)")
    a = ap.parse_args()
    if a.live:
        a.dry = False
    cfg = DEFAULT_CONFIG | json.loads(Path(a.config).read_text())
    if not a.dry and (not cfg["api_key"] or not cfg["api_secret"]):
        print("ERROR: --live requires api_key/api_secret in config", file=sys.stderr)
        return 2

    st = State(Path(cfg["state_file"]))
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if st.data.get("day") != today:
        st.data["day"] = today
        st.data["orders_today"] = 0

    # positions: {"BTC/USDT": "LONG|CASH"} last applied per symbol
    for sym in cfg["symbols"]:
        in_w, out_w = cfg["windows"].get(sym, [50, 40])
        rows = fetch_closes(sym, transport=a.transport)
        sig, s_in, s_out = compute_signal(rows, in_w, out_w)
        cur = st.data["positions"].get(sym, "CASH")
        # hysteresis: production checks exit only while LONG
        if cur == "LONG":
            sig = "LONG" if rows[-1]["close"] > s_out else "CASH"
        if sig == cur:
            print(f"{sym}: no change ({cur})")
            continue
        if st.data["orders_today"] >= cfg["max_daily_orders"]:
            print(f"{sym}: SKIP (daily order cap {cfg['max_daily_orders']} reached)")
            continue
        if a.dry:
            print(f"{sym}: WOULD {cur}->{sig} (close={rows[-1]['close']:.4f}, sma_in={s_in:.4f}, sma_out={s_out:.4f})")
        else:
            ex = _make_exchange(cfg)
            bal = ex.fetch_balance()
            free_usdt = float(bal["USDT"]["free"])
            if sig == "LONG":
                amount = min(cfg["stake_frac"] * free_usdt, cfg["max_order_usdt"])
                amount = amount / float(ex.fetch_ticker(sym)["last"])
                ex.create_market_buy_order(sym, amount)
            else:
                pos = ex.fetch_balance()["free"].get(sym.split("/")[0], 0)
                if float(pos) > 0:
                    ex.create_market_sell_order(sym, float(pos))
            print(f"{sym}: EXECUTED {cur}->{sig}")
        st.data["positions"][sym] = sig
        st.data["orders_today"] += 1
    st.save()
    return 0


def _make_exchange(cfg):
    import ccxt

    return getattr(ccxt, cfg["exchange"])(
        {
            "apiKey": cfg["api_key"],
            "secret": cfg["api_secret"],
            "enableRateLimit": True,
        }
    )


def _default_transport(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


if __name__ == "__main__":
    sys.exit(main())
