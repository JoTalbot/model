#!/usr/bin/env python3
"""T2 momentum paper-loop: daily signal (BTC close vs SMA50) + state + TG alerts.

Backtest-proven strategy (docs/aios/MOMENTUM_STRATEGIES_RESULT_2026-08-16_RU.md):
long BTC while close > SMA50 (1d), cash otherwise. This paper loop runs daily:

  1. fetch daily closes (Yahoo BTC-USD, fallback Binance spot);
  2. compute SMA50 over CLOSED bars only;
  3. signal for today = last closed close > SMA50 (same rule as the backtest);
  4. if position changes -> apply 0.15% cost, log the trade, notify Telegram;
  5. mark equity daily (close/close) and append to value log.

State: data/t2_paper_state.json ; history: data/t2_paper_equity.jsonl
Idempotent: re-running the same day does not double-log.

Usage:
    python run_t2_momentum.py [--notify] [--state FILE] [--log FILE]
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path


def _data_dir() -> Path:
    """Octopus data dir: $OCTOPUS_T2_DATA | $OCTOPUS_DATA | <repo>/data."""
    env = os.environ.get("OCTOPUS_T2_DATA") or os.environ.get("OCTOPUS_DATA")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data"


def _urls(symbol: str) -> tuple[str, str]:
    """Binance (primary) and Yahoo (fallback) URLs for a symbol like 'BTC-USD'."""
    base = symbol.split("-")[0].upper()
    binance_sym = base + "USDT"
    return (
        f"https://api.binance.com/api/v3/klines?symbol={binance_sym}&interval=1d&limit=400",
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=400d&interval=1d",
    )


UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SMA_W = 50
COST = 0.0015  # per side, same as backtest


def default_transport(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_closes(transport=None, symbol: str = "BTC-USD") -> list[dict]:
    """List of {date, close} for closed daily bars (oldest first)."""
    t = transport or default_transport
    binance_url, yahoo_url = _urls(symbol)
    errs = []
    # primary: Binance spot (эталон ликвидности)
    try:
        raw = t(binance_url)
        klines = json.loads(raw.decode())
        rows = []
        for k in klines:
            rows.append({"date": time.strftime("%Y-%m-%d", time.gmtime(k[0] / 1000)), "close": float(k[4])})
        if len(rows) >= 100:
            return rows
        errs.append(f"binance: only {len(rows)} rows")
    except Exception as e:
        errs.append(f"binance: {e}")
    # fallback: Yahoo
    try:
        raw = t(yahoo_url)
        data = json.loads(raw.decode())
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        close = res["indicators"]["quote"][0]["close"]
        rows = []
        for x, c in zip(ts, close, strict=False):
            if c is None:
                continue
            rows.append({"date": time.strftime("%Y-%m-%d", time.gmtime(x)), "close": float(c)})
        if len(rows) >= 100:
            return rows
        errs.append(f"yahoo: only {len(rows)} rows")
    except Exception as e:
        errs.append(f"yahoo: {e}")
    raise RuntimeError("; ".join(errs))


def sma(closes: list[float], w: int) -> float | None:
    if len(closes) < w:
        return None
    return sum(closes[-w:]) / w


def check_price_discrepancy(rows: list[dict], transport=None) -> str | None:
    """Cross-check the last close from Yahoo vs Binance spot; warn if > 0.5% off."""
    if not rows:
        return None
    t = transport or default_transport
    sym = "BTCUSDT" if "BTC" in rows[-1].get("_sym", "BTC-USD") else "ETHUSDT"
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
        raw = t(url)
        binance_close = float(json.loads(raw.decode())["price"])
        yahoo_close = rows[-1]["close"]
        diff = abs(binance_close - yahoo_close) / yahoo_close * 100
        if diff > 0.5:
            return f"⚠️ Расхождение цен {sym}: Yahoo {yahoo_close:.2f} vs Binance {binance_close:.2f} ({diff:.2f}%)"
    except Exception:
        return None
    return None


def compute_signal(rows: list[dict], in_w: int = SMA_W, out_w: int | None = None) -> dict:
    """Signal on the LAST CLOSED bar (no lookahead).

    in_w/out_w implement hysteresis: enter LONG when close > SMA(in_w),
    exit when close <= SMA(out_w). out_w=None -> single SMA (enter/exit same).
    """
    closes = [r["close"] for r in rows]
    last = rows[-1]
    if out_w is None:
        out_w = in_w
    s_in = sma(closes, in_w)
    s_out = sma(closes, out_w)
    if s_in is None or s_out is None:
        return {
            "date": last["date"],
            "close": last["close"],
            "sma50": None,
            "signal": "CASH",
            "reason": "not_enough_history",
        }
    # вход: close > SMA(in); выход: close <= SMA(out)
    sig = "LONG" if last["close"] > s_in else "CASH"
    # если уже в позиции (state передаётся снаружи) - выход по out_w;
    # здесь возвращаем оба уровня, решение принимает run_daily
    return {
        "date": last["date"],
        "close": last["close"],
        "sma_in": round(s_in, 2),
        "sma_out": round(s_out, 2),
        "signal": sig,
        "reason": "close_gt_sma_in" if sig == "LONG" else "close_le_sma_in",
        "in_w": in_w,
        "out_w": out_w,
    }


class T2State:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text())
        else:
            self.data = {
                "position": "CASH",
                "entry_date": None,
                "entry_price": None,
                "equity": 10000.0,
                "last_signal_date": None,
                "trades": [],
                "cash_equiv": 10000.0,
            }

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        tmp.replace(self.path)


_CTX = {"symbol": "BTC-USD"}


def run_daily(
    state_path: Path, log_path: Path, rows: list[dict], notify=None, variant: dict | None = None, entry_filter=None
) -> dict:
    variant = variant or {}
    """One daily step: compute signal, update state, log, notify on change."""
    st = T2State(state_path)
    in_w = variant.get("in_w", SMA_W)
    out_w = variant.get("out_w")
    sig = compute_signal(rows, in_w, out_w)
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    # гистерезис: выход по SMA(out), вход по SMA(in)
    if st.data["position"] == "LONG":
        # в позиции -> сигнал выхода по sma_out
        sig["signal"] = "LONG" if last["close"] > sig["sma_out"] else "CASH"
        sig["reason"] = "close_gt_sma_out" if sig["signal"] == "LONG" else "close_le_sma_out"
    else:
        sig["signal"] = "LONG" if last["close"] > sig["sma_in"] else "CASH"
        sig["reason"] = "close_gt_sma_in" if sig["signal"] == "LONG" else "close_le_sma_in"
        if sig["signal"] == "LONG" and entry_filter is not None and not entry_filter(_CTX.get("symbol", "BTC-USD")):
            sig["signal"] = "CASH"
            sig["reason"] = "meta_filter_denied"

    # idempotency: already processed this bar?
    if st.data.get("last_signal_date") == sig["date"]:
        # just re-mark equity and return current state
        return {"status": "already_processed", "signal": sig["signal"], "equity": st.data["equity"]}

    # mark previous day's PnL first (close/close while in position)
    if prev is not None and st.data["position"] == "LONG" and st.data["entry_price"]:
        st.data["equity"] *= last["close"] / prev["close"]
    # buy&hold reference (cash_equiv = always-long equity, for comparison)
    if prev is not None:
        st.data["cash_equiv"] = st.data.get("cash_equiv", 10000.0) * last["close"] / prev["close"]

    # position change? cost applies on ANY transition (same as backtest)
    if st.data["position"] != sig["signal"]:
        old = st.data["position"]
        st.data["equity"] *= 1.0 - COST
        if sig["signal"] == "LONG":
            st.data["entry_price"] = last["close"]
            st.data["entry_date"] = sig["date"]
        else:
            st.data["entry_price"] = None
            st.data["entry_date"] = None
        st.data["position"] = sig["signal"]
        st.data["trades"].append(
            {
                "date": sig["date"],
                "from": old,
                "to": sig["signal"],
                "close": last["close"],
                "sma50": sig.get("sma_in") or sig.get("sma50"),
                "equity": round(st.data["equity"], 2),
            }
        )
        if notify:
            notify(sig, old)
    st.data["last_signal_date"] = sig["date"]
    st.save()

    # append to value log
    bh_equity = st.data.get("cash_equiv", 10000.0)
    entry = {
        "date": sig["date"],
        "close": last["close"],
        "sma50": sig.get("sma_in") or sig.get("sma50"),
        "signal": sig["signal"],
        "position": st.data["position"],
        "equity": round(st.data["equity"], 2),
        "bh_equity": round(bh_equity, 2),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return {
        "status": "ok",
        "signal": sig["signal"],
        "position": st.data["position"],
        "equity": st.data["equity"],
        "sma50": sig.get("sma_in") or sig.get("sma50"),
        "close": last["close"],
    }


def tg_send(text: str) -> bool:
    token_p = Path("/etc/octopus/credentials/telegram_token")
    chat_p = Path("/etc/octopus/credentials/telegram_owner_chat_id")
    if not token_p.exists() or not chat_p.exists():
        return False
    token, chat = token_p.read_text().strip(), chat_p.read_text().strip()
    import urllib.parse

    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception:
        return False


def daily_report(symbol: str, state_path: Path) -> str | None:
    """One-line daily report (position, equity, BH) - sent every day."""
    st = T2State(state_path).data
    eq = float(st.get("equity", 10000.0))
    bh = float(st.get("cash_equiv", 10000.0))
    pct = (eq / 10000 - 1) * 100
    bh_pct = (bh / 10000 - 1) * 100
    tag = symbol.replace("-", "")
    return (
        f"📈 T2-{tag} {time.strftime('%Y-%m-%d')}: {st.get('position')} | "
        f"equity ${eq:,.0f} ({pct:+.1f}%) | BH {bh_pct:+.1f}%"
    )


def meta_allow(symbol: str) -> bool:
    """Meta-labeling filter: allow T2 entry only if the trained model says yes."""
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from meta_labeling import predict

    r = predict(symbol)
    if r is None:
        return True  # no model -> allow (fail-open)
    return bool(r.get("allow", True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTC-USD")
    ap.add_argument("--in-w", type=int, default=SMA_W)
    ap.add_argument("--out-w", type=int, default=None)
    ap.add_argument("--state", type=Path, default=None)
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--daily-report", action="store_true", help="send a one-line report every run (not only on change)")
    ap.add_argument("--meta-filter", action="store_true", help="apply meta-labeling filter before entering LONG")
    ap.add_argument("--transport", default=None, help="injectable (tests)")
    args = ap.parse_args()

    variant = {"in_w": args.in_w, "out_w": args.out_w}
    sym_tag = args.symbol.replace("-", "").lower()
    if args.state is None:
        args.state = _data_dir() / f"t2_paper_state_{sym_tag}.json"
    if args.log is None:
        args.log = _data_dir() / f"t2_paper_equity_{sym_tag}.jsonl"

    rows = fetch_closes(args.transport, args.symbol)
    global _CTX
    _CTX = {"symbol": args.symbol}
    if args.daily_report:
        report = daily_report(args.symbol, args.state)
        if report:
            tg_send(report)

    def notify(sig, old):
        txt = (
            f"📈 T2-сигнал: {sig['date']}\n"
            f"{old} -> {sig['signal']} | close {sig['close']:.0f} "
            f"SMA{int(sig.get('in_w', 50))}/{int(sig.get('out_w', sig.get('in_w', 50)))} "
            f"{sig.get('sma_in') or sig.get('sma50')}\n"
            f"причина: {sig['reason']}"
        )
        tg_send(txt)

    res = run_daily(
        args.state,
        args.log,
        rows,
        notify if args.notify else None,
        variant=variant,
        entry_filter=(meta_allow if args.meta_filter else None),
    )
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
