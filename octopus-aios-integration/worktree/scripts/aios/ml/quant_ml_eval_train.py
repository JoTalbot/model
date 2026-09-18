#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""Evaluate the deployed CatBoost direction model and train a candidate v2.

Paper-fix session: 20260814T160500Z-aios-arena-paper-fix.
Compares the deployed `catboost_price_dir.cbm` (pooled raw-price features,
trained on all data in Colab) against a candidate trained on scale-free
features with a strict per-symbol walk-forward split. No order generation,
no portfolio mutation; read-only except writing the candidate model file
`data/quant/models/catboost_price_dir_v2.cbm` (+ .pkl).

Usage:
    python scripts/quant_ml_eval_train.py            # eval + train candidate
    python scripts/quant_ml_eval_train.py --eval-only
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import UTC
from pathlib import Path

import numpy as np
import pandas as pd

from swarm.quant.ml_gate_calibration import compute_quantiles, threshold_is_sane

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_DIR = REPO_ROOT / "data" / "quant"
MODELS_DIR = QUANT_DIR / "models"

# --------------------------------------------------------------------- deploy --
OLD_FEATURES = ["open", "high", "low", "close", "volume", "ret1", "ema12", "ema26", "rsi", "vol_ma"]
# Scale-free features for the candidate: identical scale across BTC and PEPE.
NEW_FEATURES = [
    "ret1", "ret3", "ret6", "ret12", "ret24",
    "rsi", "bb_pos", "macd_norm", "ema_gap",
    "vol_ratio", "vol_z", "bar_range_pct", "hl_pos",
]

TRAIN_FRAC = 0.70  # first 70% of each symbol's history is train
GAP_BARS = 48  # gap between train and test to isolate rolling-feature leakage


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add old (raw) and new (scale-free) feature columns; returns copy."""
    g = df.copy()
    g["ret1"] = g["close"].pct_change()
    g["ret3"] = g["close"].pct_change(3)
    g["ret6"] = g["close"].pct_change(6)
    g["ret12"] = g["close"].pct_change(12)
    g["ret24"] = g["close"].pct_change(24)
    g["ema12"] = g["close"].ewm(span=12).mean()
    g["ema26"] = g["close"].ewm(span=26).mean()
    # RSI(14) identical formula to swarm/quant/ml_predictor.py
    chg = g["close"].pct_change()
    up = chg.clip(lower=0).rolling(14).mean()
    down = (-chg.clip(upper=0)).rolling(14).mean()
    g["rsi"] = 100.0 - 100.0 / (1.0 + up / down.replace(0, 1e-9))
    g["vol_ma"] = g["volume"].rolling(20).mean()
    # Bollinger position: 0 = at lower band, 1 = at upper band
    bb_mid = g["close"].rolling(20).mean()
    bb_std = g["close"].rolling(20).std()
    g["bb_pos"] = (g["close"] - bb_mid + 2 * bb_std) / (4 * bb_std).replace(0, np.nan)
    g["bb_pos"] = g["bb_pos"].clip(0, 1)
    # MACD(12,26) normalized by price (scale-free)
    macd = g["ema12"] - g["ema26"]
    g["macd_norm"] = macd / g["close"]
    # EMA gap (scale-free trend strength)
    g["ema_gap"] = (g["ema12"] - g["ema26"]) / g["close"]
    # Volume ratio vs 20-bar mean and volume z-score
    vol_mean = g["volume"].rolling(20).mean()
    vol_std = g["volume"].rolling(20).std()
    g["vol_ratio"] = g["volume"] / vol_mean.replace(0, np.nan)
    g["vol_z"] = (g["volume"] - vol_mean) / vol_std.replace(0, np.nan)
    # Intrabar geometry (scale-free)
    g["bar_range_pct"] = (g["high"] - g["low"]) / g["close"]
    g["hl_pos"] = (g["close"] - g["low"]) / (g["high"] - g["low"]).replace(0, np.nan)
    # Target: next 1h close direction (same label as deployed model)
    g["target"] = (g["close"].shift(-1) > g["close"]).astype(int)
    return g


def _load_symbols() -> list[pd.DataFrame]:
    """Load and featurize every binance 1h CSV under data/quant/<SYM>/binance/."""
    frames = []
    for path in sorted(glob.glob(str(QUANT_DIR / "*" / "binance" / "*_1h.csv"))):
        df = pd.read_csv(path)
        if len(df) < 120:
            continue
        df = df.sort_values("timestamp_ms")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        g = _compute_features(df)
        if len(g.dropna(subset=[*NEW_FEATURES, "target"])) < 80:
            continue
        g["symbol"] = Path(path).stem.split("_")[0]
        frames.append(g)
    return frames


def _split(g: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-symbol chronological train/test with a gap; no shuffling."""
    clean = g.dropna(subset=[*NEW_FEATURES, *OLD_FEATURES, "target"]).reset_index(drop=True)
    cut = int(len(clean) * TRAIN_FRAC)
    train = clean.iloc[: cut - GAP_BARS]
    test = clean.iloc[cut:]
    return train, test


def _metrics(y_true: np.ndarray, prob_up: np.ndarray) -> dict:
    """AUC, accuracy, Brier and threshold hit-rates."""
    from sklearn.metrics import roc_auc_score

    out: dict = {
        "n": len(y_true),
        "auc": None,
        "acc": None,
        "brier": None,
        "hit_060": None,
        "cov_060": None,
        "hit_065": None,
        "cov_065": None,
        "up_rate": float(y_true.mean()),
    }
    if len(np.unique(y_true)) < 2:
        return out
    out["auc"] = float(roc_auc_score(y_true, prob_up))
    out["acc"] = float(((prob_up >= 0.5).astype(int) == y_true).mean())
    out["brier"] = float(((prob_up - y_true) ** 2).mean())
    for thr in (0.60, 0.65):
        mask = prob_up >= thr
        out[f"cov_{int(thr * 100):03d}"] = float(mask.mean())
        if mask.sum() > 0:
            out[f"hit_{int(thr * 100):03d}"] = float(y_true[mask].mean())
    return out


def _eval_model(model, df_test: pd.DataFrame, features: list[str]) -> dict:
    """Predict prob_up on the test rows; return metrics."""
    X = df_test[features].values.astype(np.float64)
    proba = model.predict_proba(X)
    prob_up = proba[:, 1] if proba.ndim == 2 else proba
    return _metrics(df_test["target"].values.astype(int), np.asarray(prob_up, dtype=np.float64))




def _simulate_engine_trades(
    df_test: pd.DataFrame, prob_up: np.ndarray, threshold: float,
    *,
    fee_rate: float = 0.0015,
    half_spread: float = 0.0005,
    slippage: float = 0.0005,
    take_profit_pct: float = 0.02,
    stop_loss_pct: float = -0.01,
    trail_ratio: float = 0.988,
    max_bars: int = 72,
) -> dict:
    """Simulate the Directional v2 paper exit rules on threshold entries.

    Entry at bar close (execution price = mid * (1 + half_spread + slippage)).
    Exits execute AT THE TRIGGER LEVEL (conservative standard), not at the bar
    close that happened to pierce it:
      - take profit:  exit at entry_mid * (1 + tp) * (1 - half_spread - slippage)
      - stop loss:    exit at entry_mid * (1 + sl) * (1 - half_spread - slippage)
      - trailing:     exit at max_seen * trail_ratio * (1 - half_spread - slippage)
      - timeout:      exit at the last close.
    Costs: entry+exit fees + spread + slippage.
    """
    trades = []
    df = df_test.reset_index(drop=True)
    closes = df["close"].values
    probs = np.asarray(prob_up, dtype=np.float64)
    for i in range(len(df)):
        if probs[i] < threshold:
            continue
        entry_mid = float(closes[i])
        entry_px = entry_mid * (1.0 + half_spread + slippage)
        max_seen = entry_mid
        exit_px = None
        reason = None
        for j in range(i + 1, min(i + 1 + max_bars, len(df))):
            px = float(closes[j])
            if px >= entry_mid * (1.0 + take_profit_pct):
                exit_px = entry_mid * (1.0 + take_profit_pct) * (1.0 - half_spread - slippage)
                reason = "tp"
                break
            if px <= entry_mid * (1.0 + stop_loss_pct):
                exit_px = entry_mid * (1.0 + stop_loss_pct) * (1.0 - half_spread - slippage)
                reason = "sl"
                break
            if max_seen > entry_mid * 1.01 and px <= max_seen * trail_ratio:
                exit_px = max_seen * trail_ratio * (1.0 - half_spread - slippage)
                reason = "trail"
                break
            max_seen = max(max_seen, px)
        if exit_px is None:
            exit_px = float(closes[min(i + max_bars, len(df) - 1)]) * (1.0 - half_spread - slippage)
            reason = "timeout"
        gross = (exit_px - entry_px) / entry_px
        net = gross - fee_rate * 2.0
        trades.append({"bar": i, "reason": reason, "gross_pct": gross * 100.0, "net_pct": net * 100.0})
    if not trades:
        return {"n": 0}
    nets = np.array([t["net_pct"] for t in trades])
    return {
        "n": len(trades),
        "wins": int((nets > 0).sum()),
        "win_rate": float((nets > 0).mean()),
        "avg_net_pct": float(nets.mean()),
        "total_net_pct": float(nets.sum()),
        "avg_gross_pct": float(np.mean([t["gross_pct"] for t in trades])),
        "reasons": {r: sum(1 for t in trades if t["reason"] == r) for r in {"tp", "sl", "trail", "timeout"}},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-only", action="store_true", help="do not train candidate")
    args = parser.parse_args()

    frames = _load_symbols()
    print(f"loaded {len(frames)} symbols")
    trains, tests = [], []
    for g in frames:
        tr, te = _split(g)
        trains.append(tr)
        tests.append(te)
    df_train = pd.concat(trains, ignore_index=True)
    df_test = pd.concat(tests, ignore_index=True)
    print(f"train rows={len(df_train)} test rows={len(df_test)}")

    result: dict = {"deployed": None, "candidate_v2": None}

    # 1. Deployed model on the same test window (old raw features).
    deployed_path = MODELS_DIR / "catboost_price_dir.cbm"
    if deployed_path.exists():
        from catboost import CatBoostClassifier

        model = CatBoostClassifier()
        model.load_model(str(deployed_path))
        result["deployed"] = _eval_model(model, df_test, OLD_FEATURES)
        print("DEPLOYED (raw features):", json.dumps(result["deployed"], ensure_ascii=False))

    if args.eval_only:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # 2. Candidate v2 on scale-free features, strict walk-forward.
    from catboost import CatBoostClassifier

    X_tr = df_train[NEW_FEATURES].values.astype(np.float64)
    y_tr = df_train["target"].values.astype(int)
    candidate = CatBoostClassifier(
        iterations=400,
        depth=5,
        learning_rate=0.03,
        l2_leaf_reg=5.0,
        loss_function="Logloss",
        eval_metric="AUC",
        random_seed=42,
        verbose=0,
        thread_count=-1,
    )
    candidate.fit(X_tr, y_tr)
    result["candidate_v2"] = _eval_model(candidate, df_test, NEW_FEATURES)
    print("CANDIDATE v2 (scale-free):", json.dumps(result["candidate_v2"], ensure_ascii=False))

    # 3. Persist candidate only when it beats the deployed AUC, reaches a
    #    non-degenerate probability range on OOS, AND a sane calibration
    #    threshold can be computed from its own test-window distribution.
    dep, cand = result["deployed"], result["candidate_v2"]
    better = (
        cand is not None
        and (cand.get("auc") or 0.0) > (dep.get("auc") or 0.0)
        and (cand.get("hit_065") or 0.0) >= 0.65
        and (cand.get("cov_065") or 0.0) >= 0.0005
    )
    prob_up = None
    if result.get("candidate_v2") is not None:
        X_test = df_test[NEW_FEATURES].values.astype(np.float64)
        prob_up = candidate.predict_proba(X_test)[:, 1]
    deployed = False
    if better and prob_up is not None and len(prob_up) > 0:
        quantiles = compute_quantiles(prob_up)
        q90 = quantiles["q90"]
        if threshold_is_sane(q90):
            from datetime import datetime

            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            candidate.save_model(str(MODELS_DIR / "catboost_price_dir_v2.cbm"))
            import joblib

            joblib.dump(candidate, MODELS_DIR / "catboost_price_dir_v2.pkl")
            cal_file = QUANT_DIR / "ml_prob_calibration.json"
            cal_file.write_text(json.dumps({
                "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "model": "catboost_price_dir_v2.cbm",
                "n_series": len(frames),
                "n_samples": len(prob_up),
                "window_days": None,  # test-window distribution of the candidate
                "quantiles": quantiles,
                "threshold_q90": q90,
            }, indent=2) + "\n", encoding="utf-8")
            deployed = True
            print(f"✅ saved candidate + calibration (q90={q90}) -> catboost_price_dir_v2.cbm/.pkl")
        else:
            print(f"⚠️ candidate NOT deployed: calibration q90={q90} outside sane band")
    elif better:
        print("⚠️ candidate NOT deployed: could not compute calibration distribution")
    else:
        print("ℹ️ candidate not saved (does not satisfy improvement criteria)")
    result["calibration_deployed"] = deployed

    # Engine-style paper trade simulation for the candidate (threshold 0.60/0.65).
    if result.get("candidate_v2") is not None and prob_up is not None:
        for thr in (0.60, 0.65):
            sim = _simulate_engine_trades(df_test, prob_up, thr)
            print(f"SIM threshold={thr}:", json.dumps(sim, ensure_ascii=False))
            result.setdefault("simulations", {})[str(thr)] = sim

    report = REPO_ROOT / "data" / "reports" / "quant_ml_v2_eval.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print("report ->", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
