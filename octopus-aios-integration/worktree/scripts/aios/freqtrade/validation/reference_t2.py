#!/usr/bin/env python3
"""Reference T2 simulation (production algorithm) on local freqtrade-format data.

Mirrors run_t2_momentum.py exactly:
- state machine with hysteresis: CASH->LONG when close > SMA(in_w),
  LONG->CASH when close <= SMA(out_w); BNB/NEAR use in=out=50.
- 0.15% cost per transition; equity marked close/close while LONG.
No lookahead: decision at close of bar t, PnL applied from close t to close t+1.

Used to validate the freqtrade port (freqtrade_t2.py) on identical data.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(__import__("os").environ.get("AIOS_FREQTRADE_DATA", str(HERE / "user_data" / "data" / "okx")))

PAIRS = ["BTC", "ETH", "SOL", "BNB", "NEAR"]
WINDOWS = {"BTC": (50, 40), "ETH": (50, 40), "SOL": (50, 40), "BNB": (50, 50), "NEAR": (50, 50)}
COST = 0.0015


def load_closes(sym: str) -> list[float]:
    p = DATA / f"{sym}_USDT-1d.json"
    rows = json.loads(p.read_text())
    return [r[4] for r in rows]


def t2_equity(closes: list[float], in_w: int, out_w: int, cost: float = COST) -> tuple[list[float], list[dict]]:
    """Production state machine. Returns equity curve (per bar) and trade list."""
    n = len(closes)
    eq = [1.0] * n
    pos = "CASH"
    trades = []
    for i in range(n):
        # 1) mark PnL of the PREVIOUS day's position: close[i-1] -> close[i]
        if i > 0 and pos == "LONG" and closes[i - 1] > 0:
            eq[i] = eq[i - 1] * closes[i] / closes[i - 1]
        else:
            eq[i] = eq[i - 1]
        # 2) signal on bar i (closed bars only, incl. bar i)
        if i >= in_w - 1 and i >= out_w - 1:
            s_in = sum(closes[i + 1 - in_w : i + 1]) / in_w
            s_out = sum(closes[i + 1 - out_w : i + 1]) / out_w
            if pos == "LONG":
                sig = "LONG" if closes[i] > s_out else "CASH"
            else:
                sig = "LONG" if closes[i] > s_in else "CASH"
        else:
            sig = "CASH"
        # 3) transition cost (same order as run_daily: PnL first, then cost)
        if sig != pos:
            eq[i] *= 1.0 - cost
            trades.append({"date_i": i, "from": pos, "to": sig})
            pos = sig
    return eq, trades


def sim_open_fill(
    closes: list[float],
    opens: list[float],
    in_w: int,
    out_w: int,
    start: int,
    cost: float = COST,
) -> tuple[float, list[tuple]]:
    """Freqtrade execution model: signal at close[prev], fill at open[i].

    Matches freqtrade's backtesting engine: entry/exit orders fill at the OPEN
    of the candle following the signal candle; no exit on the entry candle.
    Used to validate the freqtrade port on an equal footing.
    Returns (final equity, trades[(side, date_i)]).
    """

    def sma(arr, w, i):
        if i < w - 1:
            return None
        return sum(arr[i - w + 1 : i + 1]) / w

    n = len(closes)
    cash, units, pos, entry_i = 1.0, 0.0, "CASH", None
    trades = []
    for i in range(start, n):
        prev = i - 1
        s_in = sma(closes, in_w, prev)
        s_out = sma(closes, out_w, prev)
        if pos == "LONG":
            sig = "LONG" if (s_out is not None and closes[prev] > s_out) else "CASH"
        else:
            sig = "LONG" if (s_in is not None and closes[prev] > s_in) else "CASH"
        if pos == "LONG" and sig == "CASH" and i == entry_i:
            sig = "LONG"  # no exit on the entry candle
        if sig != pos:
            if sig == "LONG":
                units = cash * (1.0 - cost) / opens[i]
                cash = 0.0
                entry_i = i
                trades.append(("L", i))
            else:
                cash = units * opens[i] * (1.0 - cost)
                units = 0.0
                trades.append(("X", i))
            pos = sig
    return cash + units * closes[-1], trades


def main() -> int:
    for sym in PAIRS:
        closes = load_closes(sym)
        in_w, out_w = WINDOWS[sym]
        eq, trades = t2_equity(closes, in_w, out_w)
        total = (eq[-1] - 1.0) * 100
        years = len(closes) / 365.25
        cagr = (eq[-1] ** (1 / years) - 1.0) * 100 if eq[-1] > 0 else -100.0
        dd = min(e / m - 1 for e, m in [(eq[i], max(eq[: i + 1])) for i in range(len(eq))]) * 100
        bh = (closes[-1] / closes[0] - 1.0) * 100
        print(
            f"{sym:5s} bars={len(closes):5d} trades={len(trades):3d} "
            f"T2={total:9.1f}% CAGR={cagr:6.1f}% MaxDD={dd:6.1f}% "
            f"BH={bh:9.1f}%"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
