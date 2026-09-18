#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""Feature-engineering experiment for the quant direction model.

Compares the deployed 13 scale-free features against an extended set
(+ATR%, range z, longer momentum, hour-of-day seasonality, volume median
ratio) on the SAME OOS window. Read-only; writes a comparison report.

Usage:
    python scripts/quant_ml_feature_experiment.py
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_DIR = REPO_ROOT / "data" / "quant"

BASE_FEATURES = [
    "ret1", "ret3", "ret6", "ret12", "ret24",
    "rsi", "bb_pos", "macd_norm", "ema_gap",
    "vol_ratio", "vol_z", "bar_range_pct", "hl_pos",
]
EXTRA_FEATURES = [
    "atr_pct", "range_z", "ret36", "ret48", "ret72",
    "hour_sin", "hour_cos", "vol_med_ratio",
]
FULL_FEATURES = BASE_FEATURES + EXTRA_FEATURES

TRAIN_FRAC = 0.70
GAP_BARS = 48


def _compute(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    g = df.copy()
    g["ret1"] = g["close"].pct_change()
    g["ret3"] = g["close"].pct_change(3)
    g["ret6"] = g["close"].pct_change(6)
    g["ret12"] = g["close"].pct_change(12)
    g["ret24"] = g["close"].pct_change(24)
    g["ret36"] = g["close"].pct_change(36)
    g["ret48"] = g["close"].pct_change(48)
    g["ret72"] = g["close"].pct_change(72)
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
    # Extra features
    prev_close = g["close"].shift(1)
    tr = pd.concat(
        [
            (g["high"] - g["low"]),
            (g["high"] - prev_close).abs(),
            (g["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = tr.rolling(14).mean()
    g["atr_pct"] = atr14 / g["close"]
    range_series = (g["high"] - g["low"]) / g["close"]
    g["range_z"] = (range_series - range_series.rolling(100).mean()) / range_series.rolling(100).std().replace(0, np.nan)
    g["vol_med_ratio"] = g["volume"] / g["volume"].rolling(7).median().replace(0, np.nan)
    ts_hour = pd.to_datetime(g["timestamp_ms"], unit="ms").dt.hour
    g["hour_sin"] = np.sin(2 * np.pi * ts_hour / 24.0)
    g["hour_cos"] = np.cos(2 * np.pi * ts_hour / 24.0)
    g["target"] = (g["close"].shift(-1) > g["close"]).astype(int)
    return g


def _split(g: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    clean = g.dropna(subset=[*features, "target"]).reset_index(drop=True)
    cut = int(len(clean) * TRAIN_FRAC)
    return clean.iloc[: cut - GAP_BARS], clean.iloc[cut:]


def _eval(model, df_test: pd.DataFrame, features: list[str]) -> dict:
    from sklearn.metrics import roc_auc_score

    y = df_test["target"].values.astype(int)
    proba = model.predict_proba(df_test[features].values.astype(np.float64))
    p = proba[:, 1]
    out = {
        "n": len(y),
        "auc": round(float(roc_auc_score(y, p)), 4) if len(np.unique(y)) > 1 else None,
        "hit_060": None,
        "cov_060": None,
        "hit_065": None,
        "cov_065": None,
    }
    for thr in (0.60, 0.65):
        mask = p >= thr
        key = f"cov_{int(thr * 100):03d}"
        out[key] = round(float(mask.mean()), 5)
        if mask.sum() > 0:
            out[f"hit_{int(thr * 100):03d}"] = round(float(y[mask].mean()), 4)
    return out


def main() -> int:
    from catboost import CatBoostClassifier

    frames = []
    for path in sorted(glob.glob(str(QUANT_DIR / "*" / "binance" / "*_1h.csv"))):
        df = pd.read_csv(path).sort_values("timestamp_ms")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        g = _compute(df, FULL_FEATURES)
        if len(g.dropna(subset=[*BASE_FEATURES, "target"])) < 150:
            continue
        g["symbol"] = Path(path).stem.split("_")[0]
        frames.append(g)
    print(f"loaded {len(frames)} symbols")

    report = {}
    for name, features in (("base_13", BASE_FEATURES), ("full_21", FULL_FEATURES)):
        trains, tests = [], []
        for g in frames:
            tr, te = _split(g, features)
            if len(tr) > 100 and len(te) > 50:
                trains.append(tr)
                tests.append(te)
        df_tr = pd.concat(trains, ignore_index=True)
        df_te = pd.concat(tests, ignore_index=True)
        model = CatBoostClassifier(
            iterations=400, depth=5, learning_rate=0.03, l2_leaf_reg=5.0,
            loss_function="Logloss", eval_metric="AUC", random_seed=42,
            verbose=0, thread_count=-1,
        )
        model.fit(df_tr[features].values.astype(np.float64), df_tr["target"].values.astype(int))
        report[name] = {"train_rows": len(df_tr), ** _eval(model, df_te, features)}
        print(f"{name}: {report[name]}")

    out = REPO_ROOT / "data" / "reports" / "quant_ml_feature_experiment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("report ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
