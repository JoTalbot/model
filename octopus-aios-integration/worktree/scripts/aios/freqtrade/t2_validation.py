# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy (not in prod venv); runs on ML hosts
#!/usr/bin/env python3
"""T2 validation: 5-year test, rolling windows (bootstrap-ish), SMA calibration.

Honest robustness checks for the T2 momentum strategy before real money:
  V6: 5 years (full market cycle) - BTC/ETH/SOL
  V5: rolling 2-year windows over 5 years (9 windows) - stability
  V7: SMA period calibration per symbol (20..150) - is SMA50 a plateau or a lucky point?

All logic mirrors the paper loop (close vs SMA on closed bars, 0.15% cost
per transition). Transport injectable for tests.

Usage:
    python t2_validation.py [--days 1827] [--symbols BTC-USD ETH-USD SOL-USD]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T))

import momentum_strategies as ms  # noqa: E402
from run_t2_momentum import COST  # noqa: E402


def t2_equity(closes: np.ndarray, sma_w: int = 50, cost: float = COST) -> tuple[np.ndarray, int]:
    """Simulate T2 on a close array. Returns equity curve and trade count."""
    n = len(closes)
    eq = np.ones(n)
    in_pos = False
    trades = 0
    for i in range(1, n):
        sig = False
        if i - 1 >= sma_w - 1:
            s = closes[i - sma_w : i].mean()  # SMA over CLOSED bars only
            sig = closes[i - 1] > s
        if sig and not in_pos:
            in_pos = True
            trades += 1
            eq[i] = eq[i - 1] * (1.0 - cost)
        elif not sig and in_pos:
            in_pos = False
            trades += 1
            eq[i] = eq[i - 1] * (1.0 - cost)
        else:
            eq[i] = eq[i - 1]
        if in_pos and closes[i] > 0 and closes[i - 1] > 0:
            eq[i] *= closes[i] / closes[i - 1]
    return eq, trades


def stats(eq: np.ndarray, days: int) -> dict:
    cagr = (eq[-1] ** (365.25 / days) - 1.0) * 100 if eq[-1] > 0 else -100.0
    dd = float(((eq / np.maximum.accumulate(eq)) - 1.0).min() * 100.0)
    rets = np.diff(eq) / eq[:-1]
    sharpe = float(rets.mean() / (rets.std() + 1e-12) * np.sqrt(365)) if len(rets) > 1 else 0.0
    return {"total": (eq[-1] - 1.0) * 100.0, "cagr": cagr, "maxdd": dd, "sharpe": sharpe}


def load(symbol: str, days: int) -> np.ndarray:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={days + 10}d&interval=1d"
    req = ms.urllib.request.Request(url, headers=ms.UA)
    with ms.urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    res = data["chart"]["result"][0]
    close = res["indicators"]["quote"][0]["close"]
    return np.array([c for c in close if c is not None], dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=1827)
    ap.add_argument("--symbols", nargs="+", default=["BTC-USD", "ETH-USD", "SOL-USD"])
    ap.add_argument("--windows", type=int, default=9)
    args = ap.parse_args()

    for sym in args.symbols:
        closes = load(sym, args.days)
        n = len(closes)
        print(f"\n=== {sym}: {n} дней (5 лет, полный цикл) ===")

        # V6: 5 лет SMA50
        eq5, tr5 = t2_equity(closes, 50)
        s5 = stats(eq5, n)
        bh5 = (closes[-1] / closes[0] - 1) * 100
        print(
            f"  5 лет SMA50: {s5['total']:+.1f}% (CAGR {s5['cagr']:+.1f}%, DD {s5['maxdd']:.1f}%, "
            f"Sharpe {s5['sharpe']:.2f}, {tr5} сделок) | BH {bh5:+.1f}%"
        )

        # V5: ролл-окна по 2 года (730 дней), шаг ~183 дня
        win = 730
        print("  ролл-окна 2 года:")
        pos = neg = 0
        for i in range(0, n - win + 1, max(1, (n - win) // (args.windows - 1))):
            seg = closes[i : i + win]
            eqw, _ = t2_equity(seg, 50)
            sw = stats(eqw, win)
            bhw = (seg[-1] / seg[0] - 1) * 100
            mark = "+" if sw["total"] > bhw else "-"
            if sw["total"] > 0:
                pos += 1
            else:
                neg += 1
            print(f"    {i:>4}..{i + win}: T2 {sw['total']:+7.1f}% vs BH {bhw:+7.1f}% (DD {sw['maxdd']:.0f}%) [{mark}]")
        print(f"    положительных окон: {pos}/{pos + neg}")

        # V7: калибровка SMA
        print("  калибровка SMA (5 лет):")
        best = (0, -1e9)
        for w in (20, 30, 40, 50, 60, 75, 100, 150):
            eqw, _ = t2_equity(closes, w)
            sw = stats(eqw, n)
            mark = " <-- SMA50" if w == 50 else ""
            print(f"    SMA{w}: {sw['total']:+8.1f}% (CAGR {sw['cagr']:+5.1f}%, Sharpe {sw['sharpe']:.2f}){mark}")
            if sw["total"] > best[1]:
                best = (w, sw["total"])
        print(f"    оптимум: SMA{best[0]} ({best[1]:+.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
