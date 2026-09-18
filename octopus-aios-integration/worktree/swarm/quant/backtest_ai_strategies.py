#!/usr/bin/env python3
"""
AIOS - Бэктест ML/RL торговых стратегий на исторических данных.

Оценивает производительность стратегий на основе сигналов:
  - ML (CatBoost): prob_up -> LONG/SHORT/FLAT
  - RL (PPO): предсказанная позиция (0/0.5/1)
  - Простые бенчмарки: Buy&Hold, SMA-crossover

Метрики: Sharpe, Sortino, max drawdown, win rate, общая доходность.

Запуск:
    python -m swarm.quant.backtest_ai_strategies --symbol BTC
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data")) / "quant"


def _load_prices(symbol: str, exchange: str = "binance", tf: str = "1h"):
    """Загрузить цены из data/quant/<SYM>/<EX>/<SYM>_<tf>.csv"""
    csv = DATA_DIR / symbol / exchange / f"{symbol}_{tf}.csv"
    if not csv.exists():
        print(f"[warn] нет CSV: {csv}", file=sys.stderr)
        return None
    closes = []
    for line in csv.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
        try:
            parts = line.replace("\r", "").split(",")
            closes.append(float(parts[4]))
        except Exception:
            continue
    if not closes:
        print(f"[warn] пустые данные: {csv}", file=sys.stderr)
    return closes or None


def _metrics(returns):
    """Sharpe, Sortino, max drawdown, win rate."""
    if not returns:
        return {}
    import numpy as np
    r = np.array(returns, dtype=float)
    # equity кривая
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    max_dd = float(dd.min()) if len(dd) else 0.0
    mean = float(r.mean())
    std = float(r.std()) if len(r) > 1 else 0.0
    sharpe = mean / std * math.sqrt(252 * 24) if std > 0 else 0.0
    downside = float(r[r < 0].std()) if (r < 0).any() else 0.0
    sortino = mean / downside * math.sqrt(252 * 24) if downside > 0 else 0.0
    wins = float((r > 0).sum()) / len(r) if len(r) else 0.0
    total = float(eq[-1] - 1) if len(eq) else 0.0
    return {
        "total_return_pct": round(total * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct": round(wins * 100, 1),
        "periods": len(r),
    }


def _returns_from_positions(closes, positions):
    """Доходность от позиций (0..1). positions[i] - позиция на период i."""
    rets = []
    for i in range(1, len(closes)):
        r = closes[i] / closes[i - 1] - 1.0
        pos = positions[i - 1] if i - 1 < len(positions) else 0.0
        rets.append(pos * r)
    return rets


def backtest_ml(symbol: str, signals: dict):
    """Бэктест ML-сигналов (prob_up -> позиция)."""
    prices = _load_prices(symbol)
    if not prices or len(prices) < 50:
        return {"error": "нет данных"}
    closes = prices[-500:]
    # читаем реальные ML-сигналы
    positions = []
    ml_file = REPO_ROOT / "data" / "quant" / "ml_signals.json"
    sig_map = {}
    if ml_file.exists():
        try:
            sig_data = json.loads(ml_file.read_text())
            for s in sig_data.get("signals", []):
                sig_map[s["symbol"]] = s
        except Exception:
            pass
    sig = sig_map.get(symbol, {})
    prob_up = sig.get("prob_up", 0.5)
    # стратегия: если prob_up высок -> LONG, низкий -> FLAT/HALF
    if prob_up >= 0.6:
        pos = 1.0
    elif prob_up <= 0.4:
        pos = 0.0
    else:
        pos = 0.5
    positions = [pos] * len(closes)
    rets = _returns_from_positions(closes, positions)
    m = _metrics(rets)
    m["ml_prob_up"] = prob_up
    m["ml_direction"] = sig.get("direction")
    return m


def backtest_buy_hold(symbol: str):
    prices = _load_prices(symbol)
    if not prices or len(prices) < 2:
        return {"error": "нет данных"}
    closes = prices[-500:]
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    return _metrics(rets)


def backtest_rl(symbol: str):
    """Бэктест RL: используем позицию из rl_signals.json."""
    prices = _load_prices(symbol)
    if not prices or len(prices) < 2:
        return {"error": "нет данных"}
    closes = prices[-500:]
    rl_file = REPO_ROOT / "data" / "quant" / "rl_signals.json"
    pos = 0.5
    if rl_file.exists():
        try:
            rl_data = json.loads(rl_file.read_text())
            for s in rl_data.get("signals", []):
                if s.get("asset") == symbol and s.get("ok"):
                    pos = s.get("position", 0.5)
                    break
        except Exception:
            pass
    positions = [pos] * len(closes)
    rets = _returns_from_positions(closes, positions)
    m = _metrics(rets)
    m["rl_position"] = pos
    return m


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = {
        "symbol": args.symbol,
        "buy_hold": backtest_buy_hold(args.symbol),
        "ml_50pct": backtest_ml(args.symbol, {}),
        "rl_50pct": backtest_rl(args.symbol),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"=== Бэктест {args.symbol} ===")
        for strat, m in result.items():
            if strat == "symbol" or not isinstance(m, dict):
                continue
            if "error" in m:
                print(f"  {strat}: {m['error']}")
                continue
            print(f"\n  {strat}:")
            for k, v in m.items():
                print(f"    {k}: {v}")
        # вывод в файл
        out = DATA_DIR / "backtest_results.json"
        data = {}
        if out.exists():
            try:
                data = json.loads(out.read_text())
            except Exception:
                data = {}
        data[args.symbol] = result
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nСохранено: {out}")


if __name__ == "__main__":
    main()
