#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas (not in prod venv); runs on ML hosts
"""Robustness check for the two positive OOS strategies + RSI fix.

1. Fixes RSI after resampling (was 0.00% due to missing column).
2. MA_daily_LS: long-only variant (cash instead of short).
3. Parameter sensitivity: MA (40/160, 60/240), XS k in {2,3,4},
   XS period in {5,7,10}.
4. Splits the OOS window into two halves to check stability.

Read-only. Report -> data/reports/strategy_research_robust.json
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_DIR = REPO_ROOT / "data" / "quant"
sys.path.insert(0, str(REPO_ROOT))

from quant_strategy_research import (  # noqa: E402
    COST_SIDE,
    TRAIN_FRAC,
    load_symbols,
    resample,
    sig_ma,
)

FEE = 0.0015
HALF_SPREAD = 0.0005
SLIPPAGE = 0.0005


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    d = df.copy()
    chg = d["close"].pct_change()
    up = chg.clip(lower=0).rolling(period).mean()
    down = (-chg.clip(upper=0)).rolling(period).mean()
    d["rsi"] = 100.0 - 100.0 / (1.0 + up / down.replace(0, 1e-9))
    return d


def sig_rsi2(df, lo=30, hi=70):
    rsi = df["rsi"].values
    pos = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if math.isnan(rsi[i]):
            pos[i] = 0
        elif rsi[i] < lo:
            pos[i] = 1
        elif rsi[i] > hi:
            pos[i] = -1
    return pos


def sig_ma_longonly(df, fast, slow):
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    pos = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if math.isnan(f[i]) or math.isnan(s[i]):
            pos[i] = 0
        elif f[i] > s[i]:
            pos[i] = 1
        else:
            pos[i] = 0  # cash instead of short
    return pos


def run_on_df(df: pd.DataFrame, signal_fn, test_start: float, test_end: float | None = None) -> float:
    """Equity return % for one pre-resampled series (no re-resample)."""
    closes = df["close"].values
    times = df["timestamp_ms"].values
    mask = times >= test_start
    if test_end is not None:
        mask = mask & (times < test_end)
    if mask.sum() < 40:
        return 0.0
    positions = signal_fn(df)
    if positions is None or len(positions) != len(df):
        return 0.0
    pos = 0
    ret_sum = 0.0
    for i in range(len(df)):
        if not mask[i]:
            pos = positions[i]
            continue
        if i == 0:
            continue
        r = closes[i] / closes[i - 1] - 1.0 if closes[i - 1] > 0 else 0.0
        if pos != 0:
            ret_sum += pos * r
        new_pos = positions[i - 1]
        if new_pos != pos:
            ret_sum -= COST_SIDE * (abs(new_pos) + abs(pos))
        pos = new_pos
    return ret_sum * 100.0


def main() -> int:
    symbols = load_symbols()
    lens = sorted(len(df) for df in symbols.values())
    med_len = lens[len(lens) // 2]
    test_start = 0.0
    for df in symbols.values():
        if len(df) == med_len:
            test_start = float(df["timestamp_ms"].iloc[int(med_len * TRAIN_FRAC)])
            break
    last_ts = max(int(df["timestamp_ms"].iloc[-1]) for df in symbols.values())
    mid_oos = (test_start + last_ts) / 2.0
    print(f"OOS: {int(test_start)} .. {last_ts} (mid {int(mid_oos)})")

    results: dict[str, dict] = {}

    def add(name, res):
        results[name] = res
        print(f"{name:<28} {res['pnl_pct']:>+9.2f}%  n={res['n']}")

    # --- 1. RSI fixed ---
    for hours, name, lo, hi in [(24, "RSI_daily_MR_fixed", 30, 70), (4, "RSI_4h_MR_fixed", 30, 70),
                                (24, "RSI_daily_2550", 25, 50), (24, "RSI_daily_4020", 40, 20)]:
        total_ret = 0.0
        n = 0
        per = {}
        for symbol, df in symbols.items():
            g = add_rsi(resample(df, hours))
            r = run_on_df(g, lambda d: sig_rsi2(d, lo, hi), test_start)  # noqa: B023
            if r != 0.0 or True:  # noqa: SIM222
                per[symbol] = round(r, 3)
                total_ret += r
                n += 1
        add(f"{name} [{hours}h]", {"n": n, "pnl_pct": round(total_ret / n, 3) if n else 0.0, "per_symbol": per})

    # --- 2. MA daily long/short + long-only, parameter variants ---
    for fast, slow, name in [(50, 200, "MA_daily_LS_50_200"), (40, 160, "MA_daily_LS_40_160"),
                             (60, 240, "MA_daily_LS_60_240")]:
        total_ret = 0.0
        n = 0
        per = {}
        for symbol, df in symbols.items():
            g = resample(df, 24)
            r = run_on_df(g, lambda d, f=fast, s=slow: sig_ma(d, f, s), test_start)
            per[symbol] = round(r, 3)
            total_ret += r
            n += 1
        add(f"{name} [24h]", {"n": n, "pnl_pct": round(total_ret / n, 3) if n else 0.0, "per_symbol": per})

    total_ret = 0.0
    n = 0
    for df in symbols.values():
        g = resample(df, 24)
        r = run_on_df(g, lambda d: sig_ma_longonly(d, 50, 200), test_start)
        total_ret += r
        n += 1
    add("MA_daily_LONGONLY_50_200 [24h]", {"n": n, "pnl_pct": round(total_ret / n, 3) if n else 0.0})

    # --- 3. XS mean-reversion variants ---
    daily = {s: resample(df, 24) for s, df in symbols.items()}
    all_ts = sorted({int(t) for d in daily.values() for t in d["timestamp_ms"].values})
    close_map = {s: dict(zip(d["timestamp_ms"].values, d["close"].values, strict=False)) for s, d in daily.items()}
    ret_map = {}
    for s, d in daily.items():
        c = d["close"].values
        r = np.full(len(c), np.nan)
        r[10:] = c[10:] / c[:-10] - 1.0
        ret_map[s] = dict(zip(d["timestamp_ms"].values, r, strict=False))

    def xs_meanrev(k: int, period_days: int) -> dict:
        portfolio = 0.0
        picks: list[str] = []
        bars = 0
        for t in all_ts:
            if t < test_start:
                continue
            if picks and bars > 0:
                day_ret = 0.0
                cnt = 0
                for s in picks:
                    cp = close_map[s].get(t - 24 * 3_600_000)
                    cn = close_map[s].get(t)
                    if cp and cn:
                        day_ret += cn / cp - 1.0
                        cnt += 1
                if cnt:
                    portfolio += day_ret / cnt
            bars += 1
            if bars % period_days != 0:
                continue
            scored = [(s, ret_map[s].get(t)) for s in ret_map if ret_map[s].get(t) is not None
                      and not math.isnan(ret_map[s].get(t))]
            scored.sort(key=lambda x: x[1])
            new_picks = [s for s, _ in scored[:k]]
            turnover = 2 * k / max(1, len(scored))
            portfolio -= COST_SIDE * turnover
            picks = new_picks
        days = sum(1 for t in all_ts if t >= test_start)
        return {"n": days, "pnl_pct": round(portfolio * 100.0, 3)}

    for k, p in [(3, 7), (2, 7), (4, 7), (3, 5), (3, 10)]:
        res = xs_meanrev(k, p)
        add(f"XS_meanrev_bot{k}_p{p} [1d]", res)

    # --- 4. Stability: two halves of OOS for the main candidates ---
    def oos_split(signal_fn, hours, half):
        lo_ts, hi_ts = (test_start, mid_oos) if half == 0 else (mid_oos, last_ts)
        total_ret = 0.0
        n = 0
        for df in symbols.values():
            g = resample(df, hours)
            closes = g["close"].values
            times = g["timestamp_ms"].values
            mask = (times >= lo_ts) & (times < hi_ts)
            if mask.sum() < 40:
                continue
            positions = signal_fn(g)
            if positions is None or len(positions) != len(g):
                continue
            pos = 0
            ret_sum = 0.0
            for i in range(len(g)):
                if not mask[i]:
                    pos = positions[i]
                    continue
                if i == 0:
                    continue
                r = closes[i] / closes[i - 1] - 1.0 if closes[i - 1] > 0 else 0.0
                if pos != 0:
                    ret_sum += pos * r
                new_pos = positions[i - 1]
                if new_pos != pos:
                    ret_sum -= COST_SIDE * (abs(new_pos) + abs(pos))
                pos = new_pos
            total_ret += ret_sum
            n += 1
        return round(total_ret / n * 100.0, 3) if n else 0.0

    add("MA_daily_LS half1", {"n": 33, "pnl_pct": oos_split(lambda d: sig_ma(d, 50, 200), 24, 0)})
    add("MA_daily_LS half2", {"n": 33, "pnl_pct": oos_split(lambda d: sig_ma(d, 50, 200), 24, 1)})

    report = {
        "test_start_ts": int(test_start),
        "last_ts": int(last_ts),
        "note": "costs 0.25%/side; no lookahead; equal-weight symbols",
        "results": results,
    }
    out = REPO_ROOT / "data" / "reports" / "strategy_research_robust.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("report ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
