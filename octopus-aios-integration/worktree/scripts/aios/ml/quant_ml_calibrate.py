#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""Calibrate the Directional-v2 ML gate to the deployed model's real output
distribution (owner decision 2026-08-17: strict but achievable threshold).

Scores the deployed CatBoost v2 model over the last N days of 1h candles for
every asset in data/quant/, computes quantiles of prob_up and writes
data/quant/ml_prob_calibration.json with threshold_q90.

The policy (swarm/quant/quant_directional_policy.py) then uses
effective_ml_min = min(AIOS_QUANT_ML_MIN_PROB, max(floor, threshold_q90)).

Read-only: never touches orders, portfolios or runtime state.

Usage:
    python scripts/quant_ml_calibrate.py [--window-days 365] [--out ...]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from swarm.quant.ml_gate_calibration import (
    CALIBRATION_BAND,
    compute_quantiles,
    threshold_is_sane,
)
from swarm.quant.ml_predictor import DEFAULT_FEATURES

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_DIR = REPO_ROOT / "data" / "quant"
MODELS_DIR = QUANT_DIR / "models"
DEFAULT_OUT = QUANT_DIR / "ml_prob_calibration.json"



def _features_df(g: pd.DataFrame) -> pd.DataFrame:
    """Vectorized copy of QuantMLPredictor._features_from_csv formulas
    (must stay 1:1 with swarm/quant/ml_predictor.py and
    scripts/quant_ml_eval_train.py)."""

    f = g[["open", "high", "low", "close", "volume"]].copy()
    f["ret1"] = f["close"].pct_change()
    f["ret3"] = f["close"].pct_change(3)
    f["ret6"] = f["close"].pct_change(6)
    f["ret12"] = f["close"].pct_change(12)
    f["ret24"] = f["close"].pct_change(24)
    chg = f["close"].pct_change()
    up = chg.clip(lower=0).rolling(14).mean()
    down = (-chg.clip(upper=0)).rolling(14).mean()
    f["rsi"] = 100.0 - 100.0 / (1.0 + up / down.replace(0, 1e-9))
    bb_mid = f["close"].rolling(20).mean()
    bb_std = f["close"].rolling(20).std()
    f["bb_pos"] = ((f["close"] - bb_mid + 2 * bb_std) / (4 * bb_std).replace(0, 1e-9)).clip(0, 1)
    f["ema12"] = f["close"].ewm(span=12).mean()
    f["ema26"] = f["close"].ewm(span=26).mean()
    f["macd_norm"] = (f["ema12"] - f["ema26"]) / f["close"]
    f["ema_gap"] = (f["ema12"] - f["ema26"]) / f["close"]
    vol_mean = f["volume"].rolling(20).mean()
    vol_std = f["volume"].rolling(20).std()
    f["vol_ratio"] = f["volume"] / vol_mean.replace(0, 1e-9)
    f["vol_z"] = (f["volume"] - vol_mean) / vol_std.replace(0, 1e-9)
    f["bar_range_pct"] = (f["high"] - f["low"]) / f["close"]
    f["hl_pos"] = (f["close"] - f["low"]) / (f["high"] - f["low"]).replace(0, 1e-9)
    return f.dropna(subset=DEFAULT_FEATURES)


def _pick_csv(symbol_dir: Path, symbol: str) -> Path | None:
    """Prefer binance series, otherwise the longest CSV available."""

    candidates = sorted(symbol_dir.glob(f"*/{symbol}_1h.csv"), key=lambda p: -p.stat().st_size)
    if not candidates:
        return None
    for p in candidates:
        if "binance" in str(p).lower():
            return p
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=365)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    model_path = None
    for name in ("catboost_price_dir_v2.cbm", "catboost_price_dir.cbm", "catboost_price_dir.pkl"):
        if (MODELS_DIR / name).exists():
            model_path = MODELS_DIR / name
            break
    if model_path is None:
        raise SystemExit("model not found in data/quant/models/")
    from catboost import CatBoostClassifier

    model = CatBoostClassifier()
    model.load_model(str(model_path))

    prob_up_all: list[float] = []
    n_series = 0
    for symbol_dir in sorted(QUANT_DIR.iterdir()):
        if not symbol_dir.is_dir():
            continue
        symbol = symbol_dir.name
        csv_path = _pick_csv(symbol_dir, symbol)
        if csv_path is None:
            continue
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if len(df) < 40:
            continue
        df = df.sort_values("timestamp_ms")
        if args.window_days > 0:
            cutoff = (time.time() - args.window_days * 86400.0) * 1000.0
            df = df[df["timestamp_ms"] >= cutoff]
        f = _features_df(df)
        if f.empty:
            continue
        proba = model.predict_proba(f[DEFAULT_FEATURES].to_numpy())
        prob_up_all.extend(float(p[1]) for p in proba)
        n_series += 1

    if n_series == 0 or not prob_up_all:
        raise SystemExit("no features computed; aborting (no calibration file written)")

    quantiles = compute_quantiles(prob_up_all)
    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model_path.name,
        "n_series": n_series,
        "n_samples": len(prob_up_all),
        "window_days": args.window_days,
        "quantiles": quantiles,
        "threshold_q90": quantiles["q90"],
    }
    if not threshold_is_sane(quantiles["q90"]):
        print(f"⚠️ q90={quantiles['q90']} outside sane band {CALIBRATION_BAND}; file still written for diagnostics")
        # still write, but the policy floor/cap keeps the gate fail-closed
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: n_series={n_series} n_samples={len(prob_up_all)} q90={quantiles['q90']} (q50={quantiles['q50']}, q95={quantiles['q95']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
