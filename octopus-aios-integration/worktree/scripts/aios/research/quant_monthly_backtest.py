#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas (not in prod venv); runs on ML hosts
"""Monthly backtest of the deployed Directional v2 paper algorithm.

Replays the CURRENT production rules (as deployed on 2026-08-14) as if trading
started exactly one calendar month ago. All symbols are processed SYNCHRONOUSLY
bar by bar (as in the live daemon), with a single shared portfolio:

  - signal engine: SMA3/10, RSI14, BB20, MACD12/26, ML v2 (prob_up), RL veto
    (0.0 for the 10 majors in the RL universe, None otherwise) — formulas 1:1
    with swarm/quant/quant_trading_engine.py::record_and_analyze;
  - entry gate: DirectionalV2Config owner profile (entry_mode=enabled,
    ML>=0.65, conf>=0.88, max 1 global position, DD/daily kill 0.25%,
    investment min(cash*0.2, 200) >= 10);
  - exits: TP +2% / SL -1% (intrabar via high/low, SL priority),
    trailing -1.2% from max seen after +1%, bearish exit (hold>=7200s,
    conf>=0.88, ML<=0.40), close at last price at period end;
  - costs: fee 0.15% per side, half-spread 0.05% + slippage 0.05%.

Assumptions (documented in the report): binance 1h closes used as price proxy
for the allowlisted venues; ML model trained on data including the test month
(in-sample for the ML part only); funding/orderbook neutral.

Usage:
    python scripts/quant_monthly_backtest.py [--no-ml-gate] [--output ...]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
QUANT_DIR = REPO_ROOT / "data" / "quant"
MODELS_DIR = QUANT_DIR / "models"

try:
    from dateutil.relativedelta import relativedelta
except ImportError:  # pragma: no cover
    relativedelta = None

# Owner profile (mirrors /etc/systemd/system/aios-quant-trading.service).
PROFILE = {
    "entry_mode": "enabled",
    "max_global_positions": 1,
    "max_drawdown_pct": 0.25,
    "max_daily_loss_pct": 0.25,
    "min_confidence": 0.88,
    "ml_min_prob_up": 0.65,
    "rl_veto_position": 0.30,
    "min_hold_seconds": 7200,
    "half_spread_rate": 0.0005,
    "slippage_rate": 0.0005,
    "fee_rate": 0.0015,
    "take_profit_pct": 0.02,
    "stop_loss_pct": -0.01,
    "trail_ratio": 0.988,
}

RL_ASSETS = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK", "DOT", "POL"}

FEATURES = [
    "ret1", "ret3", "ret6", "ret12", "ret24",
    "rsi", "bb_pos", "macd_norm", "ema_gap",
    "vol_ratio", "vol_z", "bar_range_pct", "hl_pos",
]


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    g = df.copy()
    g["ret1"] = g["close"].pct_change()
    g["ret3"] = g["close"].pct_change(3)
    g["ret6"] = g["close"].pct_change(6)
    g["ret12"] = g["close"].pct_change(12)
    g["ret24"] = g["close"].pct_change(24)
    g["ema12"] = g["close"].ewm(span=12).mean()
    g["ema26"] = g["close"].ewm(span=26).mean()
    chg = g["close"].pct_change()
    up = chg.clip(lower=0).rolling(14).mean()
    down = (-chg.clip(upper=0)).rolling(14).mean()
    g["rsi"] = 100.0 - 100.0 / (1.0 + up / down.replace(0, 1e-9))
    bb_mid = g["close"].rolling(20).mean()
    bb_std = g["close"].rolling(20).std()
    g["bb_pos"] = ((g["close"] - bb_mid + 2 * bb_std) / (4 * bb_std).replace(0, np.nan)).clip(0, 1)
    macd = g["ema12"] - g["ema26"]
    g["macd_norm"] = macd / g["close"]
    g["ema_gap"] = (g["ema12"] - g["ema26"]) / g["close"]
    vol_mean = g["volume"].rolling(20).mean()
    vol_std = g["volume"].rolling(20).std()
    g["vol_ratio"] = g["volume"] / vol_mean.replace(0, np.nan)
    g["vol_z"] = (g["volume"] - vol_mean) / vol_std.replace(0, np.nan)
    g["bar_range_pct"] = (g["high"] - g["low"]) / g["close"]
    g["hl_pos"] = (g["close"] - g["low"]) / (g["high"] - g["low"]).replace(0, np.nan)
    return g


def record_and_analyze(closes: list[float], ml_prob: float | None, rl_position: float | None) -> dict:
    """1:1 replica of quant_trading_engine.record_and_analyze scoring."""
    prices = closes[-50:]
    fast_period = min(3, len(prices))
    slow_period = min(10, len(prices))
    sma_fast = sum(prices[-fast_period:]) / fast_period
    sma_slow = sum(prices[-slow_period:]) / slow_period

    rsi = 50.0
    if len(prices) >= 5:
        gains = [max(prices[i] - prices[i - 1], 0) for i in range(1, len(prices))]
        losses = [max(prices[i - 1] - prices[i], 0) for i in range(1, len(prices))]
        avg_gain = sum(gains[-14:]) / min(14, len(gains))
        avg_loss = sum(losses[-14:]) / min(14, len(losses))
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        else:
            rsi = 100.0

    period_bb = min(20, len(prices))
    sma_bb = sum(prices[-period_bb:]) / period_bb
    variance = sum((p - sma_bb) ** 2 for p in prices[-period_bb:]) / period_bb
    std_dev = math.sqrt(variance)
    upper_bb = sma_bb + 2.0 * std_dev
    lower_bb = sma_bb - 2.0 * std_dev

    p12 = prices[-min(12, len(prices)):]
    p26 = prices[-min(26, len(prices)):]
    macd_line = (sum(p12) / len(p12)) - (sum(p26) / len(p26))

    current = prices[-1]
    bullish = bearish = 0
    if current <= lower_bb:
        bullish += 2
    elif current >= upper_bb:
        bearish += 2
    if rsi < 35.0:
        bullish += 2
    elif rsi > 65.0:
        bearish += 2
    if sma_fast > sma_slow:
        bullish += 1
    elif sma_fast < sma_slow:
        bearish += 1
    if macd_line > 0:
        bullish += 1
    elif macd_line < 0:
        bearish += 1
    if ml_prob is not None:
        if ml_prob >= 0.65:
            bullish += 1
        elif ml_prob <= 0.35:
            bearish += 1
    if rl_position is not None:
        if rl_position > 0.7:
            bullish += 1
        elif rl_position < 0.3:
            bearish += 1

    if bullish >= 3 and bullish > bearish:
        return {"signal": "BUY_LONG", "confidence": round(min(0.99, 0.70 + bullish * 0.06), 2),
                "bullish": bullish, "bearish": bearish}
    if bearish >= 3 and bearish > bullish:
        return {"signal": "SELL_SHORT", "confidence": round(min(0.99, 0.70 + bearish * 0.06), 2),
                "bullish": bullish, "bearish": bearish}
    return {"signal": "HOLD", "confidence": 0.50, "bullish": bullish, "bearish": bearish}


def entry_block_reason(analysis: dict, *, global_positions: int, drawdown_pct: float,
                       daily_loss_pct: float, ml_gate: bool = True) -> str | None:
    """1:1 replica of quant_directional_policy.entry_block_reason with the owner profile."""
    p = PROFILE
    ml_prob = analysis.get("ml_prob_up")
    rl_position = analysis.get("rl_position")
    if float(analysis.get("confidence", 0.0)) < p["min_confidence"]:
        return "confidence_below_min"
    if ml_gate and (ml_prob is None or float(ml_prob) < p["ml_min_prob_up"]):
        return "ml_not_confirmed"
    if rl_position is not None and float(rl_position) <= p["rl_veto_position"]:
        return "rl_veto"
    if global_positions >= p["max_global_positions"]:
        return "global_position_limit"
    if drawdown_pct >= p["max_drawdown_pct"]:
        return "global_drawdown_kill"
    if daily_loss_pct >= p["max_daily_loss_pct"]:
        return "daily_loss_kill"
    return None


def _py(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


ALLOWLIST_VENUES = ["kucoin", "bitstamp", "mexc"]


def _load_series(symbol: str, exchange: str) -> pd.DataFrame | None:
    paths = glob.glob(str(QUANT_DIR / symbol / exchange / f"{symbol}_1h.csv"))
    if not paths:
        return None
    df = pd.read_csv(paths[0]).sort_values("timestamp_ms")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    if len(df) < 400:
        return None
    return df.reset_index(drop=True)


def load_symbols(venue: str = "binance") -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    out: dict[str, pd.DataFrame] = {}
    used: dict[str, str] = {}
    symbols = sorted(
        Path(path).stem.split("_")[0]
        for path in glob.glob(str(QUANT_DIR / "*" / "binance" / "*_1h.csv"))
    )
    for symbol in symbols:
        if symbol in ("MATIC", "RNDR"):
            continue
        candidates = ALLOWLIST_VENUES if venue == "allowlist" else [venue]
        for exchange in candidates:
            df = _load_series(symbol, exchange)
            if df is not None:
                out[symbol] = df
                used[symbol] = exchange
                break
    return out, used


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/reports/monthly_backtest.md"))
    parser.add_argument("--months", type=int, default=1, help="backtest window in calendar months")
    parser.add_argument("--no-ml-gate", action="store_true",
                        help="control scenario: disable the ML>=0.65 entry filter")
    parser.add_argument("--ml-min-prob", type=float, default=0.65,
                        help="ML entry threshold (deployed effective gate: 0.5061 calibrated)")
    parser.add_argument("--free-profile", action="store_true",
                        help="signals quality run: no position limit, no DD/daily-loss kill, fixed $200 stake")
    parser.add_argument("--price-source", default="binance",
                        help="binance (default proxy) | allowlist (kucoin>bitstamp>mexc) | имя биржи")
    parser.add_argument("--trail-ratio", type=float, default=0.988,
                        help="trailing exit ratio (main A/B arm: 1.0)")
    args = parser.parse_args()
    PROFILE["ml_min_prob_up"] = args.ml_min_prob
    PROFILE["trail_ratio"] = args.trail_ratio
    ml_gate = not args.no_ml_gate
    if args.free_profile:
        tag = "free_profile_ml" if ml_gate else "free_profile_no_ml"
    else:
        tag = "current_algorithm" if ml_gate else "no_ml_gate"

    symbols, venue_used = load_symbols(args.price_source)
    print(f"loaded {len(symbols)} symbols (price source: {args.price_source})")
    last_ts = max(int(df["timestamp_ms"].iloc[-1]) for df in symbols.values())
    if relativedelta is not None:
        start_dt = datetime.fromtimestamp(last_ts / 1000, tz=UTC) - relativedelta(months=args.months)
    else:  # pragma: no cover
        start_dt = datetime.fromtimestamp(last_ts / 1000, tz=UTC) - pd.Timedelta(days=30 * args.months)
    start_ms = int(start_dt.timestamp() * 1000)

    from catboost import CatBoostClassifier

    model = CatBoostClassifier()
    model.load_model(str(MODELS_DIR / "catboost_price_dir_v2.cbm"))

    # Precompute per-symbol arrays and the union of month timestamps.
    series: dict[str, dict] = {}
    all_ts: set[int] = set()
    bh_stats: dict[str, float] = {}
    for symbol, df in symbols.items():
        feats = _compute_features(df)
        X = feats[FEATURES].values.astype(np.float64)
        probs = model.predict_proba(X)[:, 1] if len(X) else np.array([])
        times = df["timestamp_ms"].values
        mask = times >= start_ms
        idx = np.where(mask)[0]
        if len(idx) < 100:
            continue
        i0 = int(idx[0])
        month_ts = [int(t) for t in times[i0:]]
        all_ts.update(month_ts)
        by_ts = {int(times[k]): k for k in range(len(times))}
        bh_start = float(df["close"].iloc[i0])
        bh_end = float(df["close"].iloc[-1])
        bh_stats[symbol] = (bh_end / bh_start - 1.0) * 100.0
        series[symbol] = {
            "closes": df["close"].values,
            "highs": df["high"].values,
            "lows": df["low"].values,
            "times": times,
            "by_ts": by_ts,
            "probs": probs,
            "i0": i0,
        }

    cash = 1000.0
    initial = cash
    max_conc = 0
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    block_counts: dict[str, int] = {}
    history: dict[str, list[float]] = {s: [] for s in series}
    current_day = ""
    day_start_equity = initial
    total_fees = 0.0

    # Warm-up: all bars before start_ms.
    for symbol, s in series.items():
        for k in range(int(s["i0"])):
            history[symbol].append(float(s["closes"][k]))

    for ts in sorted(all_ts):
        day = datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d")
        if day != current_day:
            current_day = day
            equity_now = cash + sum(
                float(pos["qty"]) * float(pos.get("mark_price", pos["entry_mid"]))
                for pos in positions.values()
            )
            day_start_equity = equity_now

        max_conc = max(max_conc, len(positions))
        # --- exits for every symbol on this bar ---
        for symbol, s in series.items():
            k = s["by_ts"].get(ts)
            if k is None:
                continue
            price = float(s["closes"][k])
            history[symbol].append(price)
            pos = positions.get(symbol)
            if pos is None:
                continue
            entry_mid = float(pos["entry_mid"])
            invested = float(pos["invested_usd"])
            qty = float(pos["qty"])
            max_seen = max(float(pos["max_price_seen"]), price)
            pos["max_price_seen"] = max_seen
            pos["mark_price"] = price
            hi, lo = float(s["highs"][k]), float(s["lows"][k])
            exit_px = None
            reason = ""
            if lo <= entry_mid * (1.0 + PROFILE["stop_loss_pct"]):
                exit_px = entry_mid * (1.0 + PROFILE["stop_loss_pct"]) * (1.0 - PROFILE["half_spread_rate"] - PROFILE["slippage_rate"])
                reason = "stop_loss"
            elif hi >= entry_mid * (1.0 + PROFILE["take_profit_pct"]):
                exit_px = entry_mid * (1.0 + PROFILE["take_profit_pct"]) * (1.0 - PROFILE["half_spread_rate"] - PROFILE["slippage_rate"])
                reason = "take_profit"
            elif max_seen > entry_mid * 1.01 and lo <= max_seen * PROFILE["trail_ratio"]:
                exit_px = max_seen * PROFILE["trail_ratio"] * (1.0 - PROFILE["half_spread_rate"] - PROFILE["slippage_rate"])
                reason = "trailing_stop"
            else:
                ml_prob = float(s["probs"][k]) if k < len(s["probs"]) and not math.isnan(float(s["probs"][k])) else None
                analysis = record_and_analyze(history[symbol], ml_prob,
                                              0.0 if symbol in RL_ASSETS else None)
                if (analysis["signal"] == "SELL_SHORT"
                        and float(analysis["confidence"]) >= PROFILE["min_confidence"]
                        and ml_prob is not None and float(ml_prob) <= 0.40
                        and (ts - float(pos["opened_at"])) >= PROFILE["min_hold_seconds"] * 1000):
                    exit_px = price * (1.0 - PROFILE["half_spread_rate"] - PROFILE["slippage_rate"])
                    reason = "confirmed_bearish_exit"
            if exit_px is not None:
                exit_fee = exit_px * qty * PROFILE["fee_rate"]
                proceeds = exit_px * qty - exit_fee
                net_pnl = proceeds - invested
                cash += proceeds
                total_fees += exit_fee + float(pos["entry_fee_usd"])
                trades.append({
                    "symbol": symbol, "side": "LONG", "exit_reason": reason,
                    "entry_ts": _py(pos["opened_at"]), "exit_ts": _py(ts),
                    "bars_held": _py((ts - pos["opened_at"]) / 3_600_000),
                    "entry_mid": _py(entry_mid), "exit_px": _py(exit_px),
                    "invested_usd": _py(invested), "net_pnl_usd": _py(net_pnl),
                    "net_pnl_pct": _py(net_pnl / invested * 100.0),
                })
                del positions[symbol]

        # --- entries on this bar ---
        if not args.free_profile and len(positions) >= PROFILE["max_global_positions"]:
            continue
        for symbol, s in series.items():
            if symbol in positions:
                continue
            k = s["by_ts"].get(ts)
            if k is None:
                continue
            price = float(s["closes"][k])
            ml_prob = float(s["probs"][k]) if k < len(s["probs"]) and not math.isnan(float(s["probs"][k])) else None
            rl_position = 0.0 if symbol in RL_ASSETS else None
            analysis = record_and_analyze(history[symbol], ml_prob, rl_position)
            analysis["ml_prob_up"] = ml_prob
            analysis["rl_position"] = rl_position
            if analysis["signal"] != "BUY_LONG":
                continue
            equity = cash + sum(
                float(p["qty"]) * float(p.get("mark_price", p["entry_mid"]))
                for p in positions.values()
            )
            dd_pct = max(0.0, (initial - equity) / initial * 100.0)
            day_loss_pct = max(0.0, (day_start_equity - equity) / day_start_equity * 100.0) if day_start_equity > 0 else 0.0
            if args.free_profile:
                reason = entry_block_reason(
                    analysis, global_positions=0,
                    drawdown_pct=0.0, daily_loss_pct=0.0, ml_gate=ml_gate,
                )
            else:
                reason = entry_block_reason(
                    analysis, global_positions=len(positions),
                    drawdown_pct=dd_pct, daily_loss_pct=day_loss_pct, ml_gate=ml_gate,
                )
            block_counts[reason or "OK"] = block_counts.get(reason or "OK", 0) + 1
            if reason is not None:
                continue
            investment = 200.0 if args.free_profile else min(cash * 0.20, 200.0)
            if investment < 10.0:
                block_counts["minimum_order"] = block_counts.get("minimum_order", 0) + 1
                continue
            entry_fee = investment * PROFILE["fee_rate"]
            exec_px = price * (1.0 + PROFILE["half_spread_rate"] + PROFILE["slippage_rate"])
            qty = (investment - entry_fee) / exec_px
            cash -= investment
            total_fees += entry_fee
            positions[symbol] = {
                "side": "LONG", "entry_price": exec_px, "entry_mid": price,
                "qty": qty, "invested_usd": investment,
                "entry_fee_usd": entry_fee, "max_price_seen": price,
                "mark_price": price, "opened_at": ts,
                "signal_confidence": analysis["confidence"],
                "ml_prob_up": ml_prob,
            }
            if not args.free_profile:
                break  # one position at a time per bar (max 1 global)

    # Close open positions at period end.
    for symbol, pos in list(positions.items()):
        price = float(series[symbol]["closes"][-1])
        exit_px = price * (1.0 - PROFILE["half_spread_rate"] - PROFILE["slippage_rate"])
        exit_fee = exit_px * float(pos["qty"]) * PROFILE["fee_rate"]
        proceeds = exit_px * float(pos["qty"]) - exit_fee
        net_pnl = proceeds - float(pos["invested_usd"])
        cash += proceeds
        total_fees += exit_fee + float(pos["entry_fee_usd"])
        trades.append({
            "symbol": symbol, "side": "LONG", "exit_reason": "period_end",
            "entry_ts": _py(pos["opened_at"]), "exit_ts": _py(last_ts),
            "bars_held": _py((last_ts - pos["opened_at"]) / 3_600_000),
            "entry_mid": _py(pos["entry_mid"]), "exit_px": _py(exit_px),
            "invested_usd": _py(pos["invested_usd"]), "net_pnl_usd": _py(net_pnl),
            "net_pnl_pct": _py(net_pnl / pos["invested_usd"] * 100.0),
        })
        positions.pop(symbol)

    final_equity = cash
    port_pnl_pct = (final_equity - initial) / initial * 100.0
    bh_values = sorted(bh_stats.items(), key=lambda x: x[1])
    avg_bh = statistics.mean(v for _, v in bh_values)
    med_bh = statistics.median(v for _, v in bh_values)
    win_trades = [t for t in trades if t["net_pnl_usd"] > 0]

    start_dt_str = datetime.fromtimestamp(start_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    end_dt_str = datetime.fromtimestamp(last_ts / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    report = {
        "scenario": tag,
        "price_source": args.price_source,
        "period": {"start": start_dt_str, "end": end_dt_str, "bars": len(all_ts)},
        "initial_capital_usd": initial,
        "final_equity_usd": round(final_equity, 2),
        "portfolio_pnl_pct": round(port_pnl_pct, 3),
        "total_trades": len(trades),
        "wins": len(win_trades),
        "win_rate_pct": round(len(win_trades) / len(trades) * 100, 2) if trades else 0.0,
        "total_fees_usd": round(total_fees, 2),
        "max_concurrent_positions": max_conc,
        "avg_trade_pnl_pct": round(statistics.mean(t["net_pnl_pct"] for t in trades), 3) if trades else 0.0,
        "buy_hold": {
            "mean_pct": round(avg_bh, 3),
            "median_pct": round(med_bh, 3),
            "best": {"symbol": bh_values[-1][0], "pct": round(bh_values[-1][1], 3)},
            "worst": {"symbol": bh_values[0][0], "pct": round(bh_values[0][1], 3)},
            "per_symbol_pct": {k: round(v, 3) for k, v in bh_stats.items()},
        },
        "block_counts": dict(sorted(block_counts.items(), key=lambda x: -x[1])),
        "trades": [
            {k: (round(v, 6) if isinstance(v, float) else v) for k, v in t.items()}
            for t in trades
        ],
    }

    if args.free_profile:
        title = ("сигналам без портфельных kill-switch (свободный профиль, с ML gate)" if ml_gate
                 else "сигналам без портфельных kill-switch (свободный профиль, БЕЗ ML gate)")
    else:
        title = "текущему алгоритму (с ML gate)" if ml_gate else "алгоритму БЕЗ ML gate (контроль)"
    md = [
        f"# Тестовый замер: {args.months} мес. торговли по {title} (Directional v2)",
        "",
        f"**Период:** {start_dt_str} → {end_dt_str} ({args.months} календарн. мес., {len(all_ts)} баров 1h)",
        f"**Стартовый капитал:** ${initial:,.2f}",
        "",
        "## Результат алгоритма",
        "",
        f"- **Итоговый капитал: ${final_equity:,.2f}**",
        f"- **PnL портфеля: {port_pnl_pct:+.2f}%**",
        f"- Сделок: {len(trades)} (win {len(win_trades)}, {report['win_rate_pct']:.1f}%)",
        f"- Средняя сделка: {report['avg_trade_pnl_pct']:+.3f}% | Комиссии и проскальзывание: ${total_fees:.2f}",
        "",
        "## Реальная динамика валют (Buy&Hold за тот же месяц)",
        "",
        f"- **Средняя по {len(bh_values)} валютам: {avg_bh:+.2f}%** (медиана {med_bh:+.2f}%)",
        f"- Лучшая: **{bh_values[-1][0]} {bh_values[-1][1]:+.2f}%**",
        f"- Худшая: **{bh_values[0][0]} {bh_values[0][1]:+.2f}%**",
        "",
        "| Валюта | Buy&Hold % |",
        "|---|---:|",
    ]
    for sym, v in sorted(bh_stats.items(), key=lambda x: -x[1]):
        md.append(f"| {sym} | {v:+.2f} |")
    md.append("")
    md.append("## Сравнение")
    md.append("")
    delta = port_pnl_pct - avg_bh
    md.append(f"- Алгоритм {port_pnl_pct:+.2f}% vs средняя валюта {avg_bh:+.2f}% → **{delta:+.2f} п.п.**")
    md.append(f"- Алгоритм {port_pnl_pct:+.2f}% vs лучшая валюта ({bh_values[-1][0]} {bh_values[-1][1]:+.2f}%)")
    md.append(f"- Алгоритм {port_pnl_pct:+.2f}% vs худшая валюта ({bh_values[0][0]} {bh_values[0][1]:+.2f}%)")
    md.append("")
    if args.free_profile and trades:
        gross_win = sum(t["net_pnl_usd"] for t in trades if t["net_pnl_usd"] > 0)
        gross_loss = -sum(t["net_pnl_usd"] for t in trades if t["net_pnl_usd"] < 0)
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        per_asset: dict[str, list[float]] = {}
        for t in trades:
            per_asset.setdefault(t["symbol"], []).append(float(t["net_pnl_usd"]))
        md += [
            "## Качество сигналов (per-asset)",
            "",
            f"- Profit factor: {pf:.2f} (gross +${gross_win:.2f} / -${gross_loss:.2f})",
            f"- Максимум одновременных позиций: {max_conc}",
            "",
            "| Актив | Сделок | PnL $ |",
            "|---|---:|---:|",
        ]
        for sym, pnls in sorted(per_asset.items(), key=lambda x: -sum(x[1])):
            md.append(f"| {sym} | {len(pnls)} | {sum(pnls):+.2f} |")
        md.append("")
    md.append("## Блокировки входов (свободный профиль)" if args.free_profile
              else "## Блокировки входов (как в продакшене)")
    md.append("")
    for k, v in report["block_counts"].items():
        md.append(f"- {k}: {v}")
    md.append("")
    if trades:
        md.append("## Сделки")
        md.append("")
        md.append("| Актив | Вход | Выход | Причина | Баров | PnL % |")
        md.append("|---|---|---|---|---:|---:|")
        for t in trades:
            e = datetime.fromtimestamp(t["entry_ts"] / 1000, tz=UTC).strftime("%m-%d %H:%M")
            x = datetime.fromtimestamp(t["exit_ts"] / 1000, tz=UTC).strftime("%m-%d %H:%M")
            md.append(f"| {t['symbol']} | {e} | {x} | {t['exit_reason']} | {t['bars_held']:.0f} | {t['net_pnl_pct']:+.2f} |")
        md.append("")
    md.append("## Допущения")
    md.append("")
    if args.price_source == "binance":
        md.append("- Цены: binance 1h как прокси разрешённых бирж (kucoin/bitstamp/mexc — нет месяца локальной истории).")
    else:
        from collections import Counter
        vc = Counter(venue_used.values())
        vtxt = ", ".join(f"{k}: {v}" for k, v in sorted(vc.items(), key=lambda x: -x[1]))
        md.append(f"- Цены: реальные 1h-серии бирж (price-source={args.price_source}; {vtxt}).")
    md.append("- ML-модель обучена на данных, включающих тестовый месяц (in-sample только для ML-части; индикаторная часть честная).")
    md.append("- Funding/orderbook нейтральны (0 / BALANCED).")
    md.append("- TP/SL исполняются по уровням при пересечении high/low бара; SL приоритетнее TP.")
    if args.free_profile:
        md.append("- Свободный профиль: без лимита позиций / DD-kill / daily-kill; каждый вход — фиксированные $200, лимит кэша не применяется (синтетический учёт).")
    else:
        md.append("- Все активы обрабатываются синхронно по барам; портфель единый ($1000), максимум 1 позиция (owner-профиль).")
    md.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(md), encoding="utf-8")
    json_out = args.output.with_suffix(f".{tag}.json")
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report -> {args.output} ({tag})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
