# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy (not in prod venv); runs on ML hosts
#!/usr/bin/env python3
"""Factor strategies on daily data: trend-following & cross-sectional momentum.

These are the classic systematic factors that historically worked in crypto
(and other markets) on WEEK/MONTH horizons - a different class from the
hourly directional trading we proved has no edge.

Variants (a-priori, fixed BEFORE looking at results):
  T1: Time-series momentum BTC  - long BTC when close > SMA200, else flat
  T2: Time-series momentum BTC  - long BTC when close > SMA50, else flat
  T3: SMA crossover (50/200) on each of the 14 symbols (long when 50>200)
  M1: Cross-sectional momentum - monthly rebalance into top-5 of past-90d returns
  M2: Cross-sectional momentum - top-5 of past-30d returns (faster)
  M3: Cross-sectional momentum - top-5 of past-60d returns
  C1: Combo: CS momentum (top-5, 90d) + only when BTC > SMA200 (trend filter)

Costs: 0.1% per trade (spot taker), slippage 0.05% -> 0.15% per side.
Metrics per variant: CAGR, max drawdown, Sharpe (daily), total PnL %, n trades,
and OOS split (last 30% of the window, parameters fixed a-priori).

Transport injectable for tests. Usage:
    python momentum_strategies.py [--symbols BTC ETH ...] [--days 731]
        [--out data/reports/momentum_strategies.md]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import numpy as np

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range={}d&interval=1d"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

COST = 0.0015  # fee 0.1% + slippage 0.05% per side

DEFAULT_SYMBOLS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
    "BNB-USD",
    "DOGE-USD",
    "ADA-USD",
    "LINK-USD",
    "AVAX-USD",
    "UNI-USD",
    "NEAR-USD",
    "LTC-USD",
    "DOT-USD",
    "TRX-USD",
]
SIMPLE = {
    "BTC-USD": "BTC",
    "ETH-USD": "ETH",
    "SOL-USD": "SOL",
    "XRP-USD": "XRP",
    "BNB-USD": "BNB",
    "DOGE-USD": "DOGE",
    "ADA-USD": "ADA",
    "LINK-USD": "LINK",
    "AVAX-USD": "AVAX",
    "UNI-USD": "UNI",
    "NEAR-USD": "NEAR",
    "LTC-USD": "LTC",
    "DOT-USD": "DOT",
    "TRX-USD": "TRX",
}


def default_transport(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_daily(transport, symbol: str, days: int) -> list[dict]:
    url = YAHOO.format(symbol, days)
    raw = transport(url)
    data = json.loads(raw.decode())
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    rows = []
    for t, c in zip(ts, close, strict=False):
        if c is None:
            continue
        rows.append({"ts": int(t), "date": time.strftime("%Y-%m-%d", time.gmtime(t)), "close": float(c)})
    return rows


def load_all(transport, symbols, days) -> dict[str, np.ndarray]:
    """ts-aligned close arrays (union of days)."""
    out = {}
    frames = {}
    for s in symbols:
        rows = fetch_daily(transport, s, days)
        frames[s] = {r["ts"]: r["close"] for r in rows}
    all_ts = sorted(set().union(*[set(f.keys()) for f in frames.values()]))
    for s in symbols:
        f = frames[s]
        out[s] = np.array([f.get(t, np.nan) for t in all_ts])
    return out, np.array(all_ts)


def sma(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    for i in range(w - 1, len(x)):
        out[i] = np.nanmean(x[i - w + 1 : i + 1])
    return out


def returns_nd(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    for i in range(n, len(x)):
        out[i] = x[i] / x[i - n] - 1.0
    return out


def run_variant(name: str, closes: dict[str, np.ndarray], ts: np.ndarray, variant: dict) -> dict:
    """Backtest a variant: returns daily equity curve & stats."""
    n = len(ts)
    weights: dict[str, float] = {}
    cash_frac = 0.0
    equity = np.zeros(n)
    turnover = 0.0
    n_trades = 0

    kind = variant["kind"]
    for i in range(n):
        # --- determine target weights for day i (using data up to i-1: NO lookahead)
        if i == 0:
            equity[i] = 1.0
            continue
        new_w: dict[str, float] = {}
        new_cash = 0.0
        if kind == "ts_btc":
            btc = closes["BTC-USD"]
            if not np.isnan(btc[i - 1]) and not np.isnan(sma(btc, 200)[i - 1]) and btc[i - 1] > sma(btc, 200)[i - 1]:
                new_w["BTC-USD"] = 1.0
            else:
                new_cash = 1.0
        elif kind == "ts_btc50200":
            btc = closes["BTC-USD"]
            s50 = sma(btc, 50)[i - 1]
            s200 = sma(btc, 200)[i - 1]
            if not np.isnan(s50) and not np.isnan(s200) and btc[i - 1] > s50 and s50 > s200:
                new_w["BTC-USD"] = 1.0
            else:
                new_cash = 1.0
        elif kind == "ts_btc50":
            sym = variant.get("sym", "BTC-USD")
            btc = closes[sym]
            if not np.isnan(btc[i - 1]) and not np.isnan(sma(btc, 50)[i - 1]) and btc[i - 1] > sma(btc, 50)[i - 1]:
                new_w[sym] = 1.0
            else:
                new_cash = 1.0
        elif kind == "sma_cross":
            # each symbol: long if SMA50>SMA200
            for s in closes:
                c = closes[s]
                s50 = sma(c, 50)[i - 1]
                s200 = sma(c, 200)[i - 1]
                if not np.isnan(s50) and not np.isnan(s200) and s50 > s200:
                    new_w[s] = 1.0 / 14
                else:
                    new_cash += 1.0 / 14
        elif kind in ("cs_mom", "cs_mom_trend"):
            look = variant.get("lookback", 90)
            rebal = variant.get("rebalance_days", 21)  # monthly rebalance
            if i > 200 and (i - 1) % rebal == 0:
                mom = {}
                for s in closes:
                    c = closes[s]
                    r = returns_nd(c, look)
                    if not np.isnan(r[i - 1]):
                        mom[s] = r[i - 1]
                if mom:
                    top = sorted(mom, key=mom.get, reverse=True)[:5]
                    if kind == "cs_mom_trend":
                        btc = closes["BTC-USD"]
                        s200 = sma(btc, 200)[i - 1]
                        if np.isnan(s200) or btc[i - 1] <= s200:
                            new_cash = 1.0
                        else:
                            for s in top:
                                new_w[s] = 0.2
                    else:
                        for s in top:
                            new_w[s] = 0.2
                else:
                    new_cash = 1.0
            elif kind in ("cs_mom", "cs_mom_trend") and i > 200:
                # between rebalances: keep previous weights
                new_w = dict(weights)
                new_cash = cash_frac

        # --- rebalance: compute turnover from previous weights
        prev = weights
        for s in set(prev) | set(new_w):
            delta = abs(new_w.get(s, 0.0) - prev.get(s, 0.0))
            turnover += delta
        n_trades += sum(1 for s in set(prev) | set(new_w) if abs(new_w.get(s, 0.0) - prev.get(s, 0.0)) > 1e-9)
        weights = new_w
        cash_frac = new_cash

        # --- day PnL: portfolio return = sum(w * asset_ret) - costs on turnover
        ret = 0.0
        for s, w in weights.items():
            c = closes[s]
            if i > 0 and not np.isnan(c[i]) and not np.isnan(c[i - 1]) and c[i - 1] > 0:
                ret += w * (c[i] / c[i - 1] - 1.0)
        cost = turnover * COST
        equity[i] = equity[i - 1] * (1.0 + ret - cost)
        turnover = 0.0

    # metrics
    dd = float(((equity / np.maximum.accumulate(equity)) - 1.0).min())
    days = n
    cagr = (equity[-1] ** (365.25 / days) - 1.0) * 100 if equity[-1] > 0 else -100.0
    rets = np.diff(equity) / equity[:-1]
    sharpe = float(rets.mean() / (rets.std() + 1e-12) * np.sqrt(365)) if len(rets) > 1 else 0.0
    total = (equity[-1] - 1.0) * 100.0
    return {
        "name": name,
        "total_pct": total,
        "cagr": cagr,
        "max_dd": dd * 100,
        "sharpe": sharpe,
        "n_trades": n_trades,
        "equity": equity,
    }


VARIANTS = [
    ("T1: TS-момент BTC (SMA200)", {"kind": "ts_btc"}),
    ("T2: TS-момент BTC (SMA50)", {"kind": "ts_btc50"}),
    ("T4: SMA50 + фильтр 50>200 (BTC)", {"kind": "ts_btc50200"}),
    ("T3: SMA-кроссовер 50/200 (14 активов)", {"kind": "sma_cross"}),
    ("M1: CS-момент топ-5 (90д, мес.)", {"kind": "cs_mom", "lookback": 90}),
    ("M2: CS-момент топ-5 (30д)", {"kind": "cs_mom", "lookback": 30}),
    ("M3: CS-момент топ-5 (60д)", {"kind": "cs_mom", "lookback": 60}),
    ("C1: CS-момент 90д + тренд-фильтр BTC>SMA200", {"kind": "cs_mom_trend", "lookback": 90}),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--days", type=int, default=731)
    ap.add_argument("--out", type=Path, default=Path("data/reports/momentum_strategies.md"))
    ap.add_argument(
        "--eval-last-days",
        type=int,
        default=0,
        help="оценить PnL за последние N дней (как будто старт N дней назад); 0 = выкл",
    )
    args = ap.parse_args()

    closes, ts = load_all(default_transport, args.symbols, args.days)
    print(f"данных: {len(args.symbols)} активов x {len(ts)} дней", flush=True)

    # OOS split: last 30% of days (params fixed a-priori)
    oos_start = int(len(ts) * 0.7)

    print(f"\n{'Вариант':<40} {'PnL%':>8} {'CAGR%':>7} {'MaxDD%':>7} {'Sharpe':>6} {'сделок':>6}", flush=True)
    print("-" * 85, flush=True)
    results = []
    for name, var in VARIANTS:
        r = run_variant(name, closes, ts, var)
        results.append(r)
        # OOS metrics
        eq_oos = r["equity"][oos_start:]
        eq_oos = eq_oos / eq_oos[0]
        dd_oos = float(((eq_oos / np.maximum.accumulate(eq_oos)) - 1.0).min())
        days_oos = len(eq_oos)
        cagr_oos = (eq_oos[-1] ** (365.25 / days_oos) - 1.0) * 100 if eq_oos[-1] > 0 else -100.0
        # last-window metrics (as-if-started N days ago)
        last_pnl = last_dd = None
        if args.eval_last_days > 0 and len(r["equity"]) > args.eval_last_days:
            eq_win = r["equity"][-args.eval_last_days :]
            eq_win = eq_win / eq_win[0]
            last_pnl = (eq_win[-1] - 1.0) * 100
            last_dd = float(((eq_win / np.maximum.accumulate(eq_win)) - 1.0).min()) * 100
            r["last_pnl_pct"] = last_pnl
            r["last_dd_pct"] = last_dd
        extra = f" | last{args.eval_last_days}d: {last_pnl:+.1f}% DD {last_dd:.1f}%" if last_pnl is not None else ""
        print(
            f"{name:<40} {r['total_pct']:>+7.1f}% {r['cagr']:>+6.1f}% {r['max_dd']:>6.1f}% "
            f"{r['sharpe']:>6.2f} {r['n_trades']:>6} | OOS: {cagr_oos:+.1f}% DD {dd_oos * 100:.1f}%{extra}",
            flush=True,
        )

    # BTC BH
    bh = (closes["BTC-USD"][-1] / closes["BTC-USD"][0] - 1.0) * 100
    print(f"\nBTC buy&hold за период: {bh:+.1f}%", flush=True)

    md = [
        "# Факторные стратегии на дневных данных (2 года)",
        "",
        f"Данные: {len(args.symbols)} активов, {len(ts)} дней | издержки {COST * 100:.2f}%/сторона",
        "Параметры зафиксированы ДО просмотра (a-priori); OOS = последние 30%.",
        "",
    ]
    if args.eval_last_days > 0:
        md += [
            f"| Вариант | PnL % | CAGR % | MaxDD % | Sharpe | Сделок | OOS CAGR % | last{args.eval_last_days}d PnL% | last{args.eval_last_days}d DD% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    else:
        md += [
            "| Вариант | PnL % | CAGR % | MaxDD % | Sharpe | Сделок | OOS CAGR % |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    for r in results:
        eq_oos = r["equity"][oos_start:] / r["equity"][oos_start]
        dd_oos = float(((eq_oos / np.maximum.accumulate(eq_oos)) - 1.0).min())
        cagr_oos = (eq_oos[-1] ** (365.25 / len(eq_oos)) - 1.0) * 100
        row = (
            f"| {r['name']} | {r['total_pct']:+.1f} | {r['cagr']:+.1f} | {r['max_dd']:.1f} | "
            f"{r['sharpe']:.2f} | {r['n_trades']} | {cagr_oos:+.1f} |"
        )
        if args.eval_last_days > 0:
            lp = r.get("last_pnl_pct")
            ld = r.get("last_dd_pct")
            row += f" {lp:+.1f} | {ld:.1f} |" if lp is not None else " — | — |"
        md.append(row)
    md += [
        "",
        f"**BTC buy&hold: {bh:+.1f}%**",
        "",
        "**Критерий доходности:** OOS CAGR > 0 и MaxDD < 40% и Sharpe > 0.5.",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
