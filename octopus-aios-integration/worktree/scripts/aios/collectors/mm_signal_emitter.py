#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 3): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy (not in prod venv); runs on ML hosts
"""V4 prototype: live signal emitter (trained model) -> Telegram, with accuracy tracking.

For each configured symbol: trains a CatBoost h1-direction model on ALL available
ws data (movement-only target), then predicts the CURRENT direction from the latest
snapshots. When confidence is high (prob_up > up_thr or < down_thr) and the symbol
is not already covered, sends an UP/DOWN signal to the owner's Telegram and logs the
emission for later accuracy scoring (realized direction is checked by
mm_signal_live_monitor-style verification in the log).

Owner-only channel for now; the same pipeline becomes the subscription product if
live accuracy holds over days.

Usage:
    python scripts/mm_signal_emitter.py [--symbols ETH BNB] [--up-thr 0.60] [--down-thr 0.40]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
DB = DATA / "quant" / "orderbooks.sqlite"
LOG = DATA / "reports" / "mm_signal_emitted.jsonl"


def load_ws(symbol: str, limit: int = 2000) -> list[dict]:
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


def load_trades(symbol: str, limit: int = 300) -> list[dict]:
    """Recent trade-flow aggregates (buy_frac per 5s bucket)."""
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT ts, buy_vol, sell_vol, buy_frac FROM trades_ws WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, limit)
    ).fetchall()
    con.close()
    return [{"ts": r[0], "buy": r[1], "sell": r[2], "frac": r[3]} for r in reversed(rows)]


def build_features(snaps: list[dict], trades: list[dict] | None = None) -> tuple[np.ndarray, list[str]]:
    n = len(snaps)
    mids = np.array([s["mid"] for s in snaps])
    # trade-flow: for each snapshot, the most recent buy_frac at ts<=snap.ts
    flow = {}
    if trades:
        flow = {t["ts"]: t["frac"] for t in trades}
    flow_ts = sorted(flow)

    def buy_frac_at(ts):
        import bisect

        j = bisect.bisect_right(flow_ts, ts) - 1
        return flow[flow_ts[j]] if j >= 0 else 0.5

    F = []
    for i in range(n):
        s = snaps[i]
        bd1 = book_vol(s["bids"], 1)
        ad1 = book_vol(s["asks"], 1)
        bd5 = book_vol(s["bids"], 5)
        ad5 = book_vol(s["asks"], 5)
        bd10 = book_vol(s["bids"], 10)
        ad10 = book_vol(s["asks"], 10)
        obi1 = (bd1 - ad1) / (bd1 + ad1 + 1e-12)
        obi5 = (bd5 - ad5) / (bd5 + ad5 + 1e-12)
        obi10 = (bd10 - ad10) / (bd10 + ad10 + 1e-12)
        micro = (s["ask"] * bd1 + s["bid"] * ad1) / (bd1 + ad1 + 1e-12)
        spread = (s["ask"] - s["bid"]) / mids[i] * 1e4 if mids[i] else 0.0
        ret1 = (mids[i] / mids[i - 1] - 1) * 1e4 if i > 0 and mids[i - 1] else 0.0
        bf = buy_frac_at(s["ts"])
        F.append(
            {
                "obi1": obi1,
                "obi5": obi5,
                "obi10": obi10,
                "micro_off": (micro - mids[i]) / mids[i] * 1e4 if mids[i] else 0.0,
                "spread_bps": spread,
                "ret1": ret1,
                "buy_frac": bf,
                "buy_frac_rev": 0.5 - bf,
            }
        )
    names = list(F[0].keys())
    X = np.array([[F[i][k] for k in names] for i in range(n)])
    return X, names


def train_model(snaps: list[dict]):
    from catboost import CatBoostClassifier

    sym = snaps[0].get("_sym", "ETH")
    trades = load_trades(sym)
    X, names = build_features(snaps, trades)
    mids = np.array([s["mid"] for s in snaps])
    times = np.array([s["ts"] for s in snaps])
    y = np.zeros(len(snaps))
    mov = np.zeros(len(snaps), dtype=bool)
    for i in range(len(snaps)):
        j = int(np.searchsorted(times, times[i] + 60, side="left"))
        if j < len(snaps):
            y[i] = 1.0 if mids[j] > mids[i] else 0.0
            mov[i] = mids[j] != mids[i]
    sel = mov
    if sel.sum() < 100:
        return None, None, names
    m = CatBoostClassifier(
        iterations=300,
        depth=4,
        learning_rate=0.05,
        loss_function="Logloss",
        eval_metric="AUC",
        random_seed=42,
        verbose=0,
    )
    m.fit(X[sel], y[sel].astype(int))
    return m, X, names


def cred(name: str) -> str | None:
    p = Path("/etc/octopus/credentials") / name
    return p.read_text().strip() if p.exists() else None


def load_subscribers() -> list[dict]:
    """Active subscribers from data/quant_subscriptions.json."""
    from datetime import datetime

    p = DATA / "quant_subscriptions.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text())
        today = datetime.now().date().isoformat()
        return [
            s for s in d.get("subscribers", []) if s.get("active") and (not s.get("expires") or s["expires"] >= today)
        ]
    except Exception:
        return []


def broadcast(token: str, owner_chat: str, text: str) -> int:
    """Send to owner + all active subscribers; returns count sent."""
    sent = 0
    targets = {owner_chat}
    for s in load_subscribers():
        targets.add(str(s.get("chat_id")))
    for c in targets:
        if send(token, c, text):
            sent += 1
    return sent


def send(t: str, c: str, text: str) -> bool:
    data = urllib.parse.urlencode({"chat_id": c, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{t}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="+", default=["ETH", "BNB"])
    ap.add_argument("--up-thr", type=float, default=0.60)
    ap.add_argument("--down-thr", type=float, default=0.40)
    ap.add_argument("--min-rows", type=int, default=400)
    args = ap.parse_args()

    token, chat = cred("telegram_token"), cred("telegram_owner_chat_id")
    msgs = []
    emitted = []
    for sym in args.symbols:
        snaps = load_ws(sym)
        for s in snaps:
            s["_sym"] = sym
        if len(snaps) < args.min_rows:
            print(f"{sym}: only {len(snaps)} rows, skip", flush=True)
            continue
        model, X, _names = train_model(snaps)
        if model is None:
            print(f"{sym}: insufficient movements, skip", flush=True)
            continue
        p = float(model.predict_proba(X[-1:])[0, 1])
        sig = "UP" if p >= args.up_thr else ("DOWN" if p <= args.down_thr else "FLAT")
        entry = {"ts": time.time(), "symbol": sym, "prob_up": round(p, 3), "direction": sig, "mid": snaps[-1]["mid"]}
        emitted.append(entry)
        line = json.dumps(entry, ensure_ascii=False)
        with open(LOG, "a") as f:
            f.write(line + "\n")
        print(line, flush=True)
        # R1 (2026-08-15): gross PnL of signal trades ≈ 0 after crossing spread;
        # fees dominate. Broadcasting signals would sell false value -> DIAGNOSTIC
        # mode: log signals, do NOT push to Telegram. Re-enable only if signal
        # economics turn positive (e.g. maker execution).
        if sig != "FLAT" and token and chat:
            msgs.append(f"{sym}: <b>{sig}</b> (prob_up={p:.2f}, mid={snaps[-1]['mid']:.4f})")
    if msgs:
        print(f"[diagnostic] {len(msgs)} signal(s) logged, not broadcast (R1: gross PnL≈0, fees dominate)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
