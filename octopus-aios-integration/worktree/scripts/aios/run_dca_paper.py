#!/usr/bin/env python3
"""Long-term DCA portfolio paper tracker (daily mark-to-market).

Config: data/dca_portfolio.json
  {
    "weekly_amount_usd": 1000,
    "weights": {"BTC": 0.1, "ETH": 0.1, ...},        # equal-weight top-10 default
    "fee_rate": 0.001,
    "rebalance_quarterly": true,
    "start_date": "2026-08-15"
  }
State: data/dca_paper_state.json (deposits, holdings, cash, fees)
Value history: data/dca_paper_value.jsonl (one line per mark)

On every run: if a weekly deposit is due -> deposit & buy at live binance spot
prices; quarterly rebalance if due; then mark to market and append the value line.

Usage:
    python scripts/run_dca_paper.py [--once]
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))

_port = os.environ.get("DCA_CONFIG", "dca_portfolio")
CONFIG = DATA / f"{_port}.json"
if _port == "dca_portfolio":
    # keep legacy filenames for the original portfolio
    STATE = DATA / "dca_paper_state.json"
    VALUE_LOG = DATA / "dca_paper_value.jsonl"
else:
    suffix = _port.replace("dca_portfolio_", "").replace("dca_", "")
    STATE = DATA / f"dca_paper_state_{suffix}.json"
    VALUE_LOG = DATA / f"dca_paper_value_{suffix}.jsonl"

DEFAULT_WEIGHTS = {
    "BTC": 0.10,
    "ETH": 0.10,
    "SOL": 0.10,
    "XRP": 0.10,
    "BNB": 0.10,
    "DOGE": 0.10,
    "TRX": 0.10,
    "TON": 0.10,
    "ADA": 0.10,
    "LINK": 0.10,
}


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Live binance spot prices (public API)."""
    out = {}
    for s in symbols:
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={s}USDT"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                out[s] = float(json.loads(r.read().decode())["price"])
        except Exception as e:
            print(f"  price {s} fail: {e}", flush=True)
    return out


def load_config() -> dict:
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text())
    else:
        cfg = {}
    cfg.setdefault("weekly_amount_usd", 1000.0)
    cfg.setdefault("mode", "dca")  # "dca" | "va" (value-averaging)
    cfg.setdefault("va_cap_mult", 2.0)  # max weekly contribution = weekly * cap
    cfg.setdefault("weights", DEFAULT_WEIGHTS)
    cfg.setdefault("fee_rate", 0.001)
    cfg.setdefault("rebalance_quarterly", True)
    cfg.setdefault("start_date", datetime.now(UTC).strftime("%Y-%m-%d"))
    w = cfg["weights"]
    tot = sum(w.values())
    cfg["weights"] = {k: v / tot for k, v in w.items()}
    return cfg


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {
        "last_deposit": None,
        "last_rebalance": None,
        "holdings": {},
        "cash_usd": 0.0,
        "deposited_usd": 0.0,
        "fees_usd": 0.0,
        "buys": [],
    }


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2))


def mark_value(state: dict, prices: dict[str, float]) -> float:
    val = state["cash_usd"]
    for s, qty in state["holdings"].items():
        px = prices.get(s)
        if px:
            val += qty * px
    return val


def main() -> int:
    cfg = load_config()
    state = load_state()
    today = datetime.now(UTC).date()
    start = datetime.strptime(cfg["start_date"], "%Y-%m-%d").date()
    weights = cfg["weights"]
    symbols = list(weights)

    prices = fetch_prices(symbols)
    if not prices:
        print("no prices, abort", flush=True)
        return 1

    # weekly deposit
    if state["last_deposit"] is None:
        due = today >= start
    else:
        last = datetime.strptime(state["last_deposit"], "%Y-%m-%d").date()
        due = (today - last).days >= 7

    if due:
        amount = cfg["weekly_amount_usd"]
        if cfg.get("mode") == "va":
            # value-averaging: bring portfolio value to the planned path
            val_now = mark_value(state, prices)
            weeks = max(1, (today - start).days // 7 + 1)
            planned = cfg["weekly_amount_usd"] * weeks
            gap = planned - val_now
            amount = max(
                0.0, min(gap, cfg["weekly_amount_usd"] * cfg.get("va_cap_mult", 2.0))
            )
        state["cash_usd"] += amount
        state["deposited_usd"] += amount
        state["last_deposit"] = today.isoformat()
        for s, w in weights.items():
            px = prices.get(s)
            if not px:
                continue
            net = amount * w * (1.0 - cfg["fee_rate"])
            qty = net / px
            state["holdings"][s] = state["holdings"].get(s, 0.0) + qty
            state["cash_usd"] -= amount * w
            state["fees_usd"] += amount * w * cfg["fee_rate"]
            state["buys"].append(
                {
                    "date": today.isoformat(),
                    "symbol": s,
                    "price": px,
                    "qty": qty,
                    "usd": amount * w,
                }
            )
        print(f"deposit {amount:.0f}$ on {today}", flush=True)

    # quarterly rebalance
    if cfg["rebalance_quarterly"] and state["last_rebalance"] is not None:
        last_r = datetime.strptime(state["last_rebalance"], "%Y-%m-%d").date()
        if (today - last_r).days >= 90:
            val = mark_value(state, prices)
            for s, w in weights.items():
                px = prices.get(s)
                if not px:
                    continue
                cur = state["holdings"].get(s, 0.0) * px
                target = val * w
                diff = target - cur
                if diff > 0:
                    net = diff * (1.0 - cfg["fee_rate"])
                    state["holdings"][s] = state["holdings"].get(s, 0.0) + net / px
                    state["cash_usd"] -= diff
                    state["fees_usd"] += diff * cfg["fee_rate"]
                elif diff < 0:
                    sell = min(state["holdings"].get(s, 0.0), -diff / px)
                    state["holdings"][s] -= sell
                    state["cash_usd"] += sell * px * (1.0 - cfg["fee_rate"])
                    state["fees_usd"] += sell * px * cfg["fee_rate"]
            state["last_rebalance"] = today.isoformat()
            print(f"quarterly rebalance on {today}", flush=True)
    elif state["last_rebalance"] is None:
        state["last_rebalance"] = today.isoformat()

    val = mark_value(state, prices)
    line = {
        "date": today.isoformat(),
        "value_usd": round(val, 2),
        "deposited_usd": round(state["deposited_usd"], 2),
        "fees_usd": round(state["fees_usd"], 4),
        "cash_usd": round(state["cash_usd"], 2),
        "prices": {k: round(v, 6) for k, v in prices.items()},
    }
    with open(VALUE_LOG, "a") as f:
        f.write(json.dumps(line) + "\n")
    save_state(state)
    pnl = val - state["deposited_usd"]
    print(
        f"value={val:.2f}$ deposited={state['deposited_usd']:.2f}$ "
        f"pnl={pnl:+.2f}$ ({pnl / state['deposited_usd'] * 100:+.2f}%)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
