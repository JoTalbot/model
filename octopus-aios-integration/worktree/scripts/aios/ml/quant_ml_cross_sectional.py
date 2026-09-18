#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""Cross-sectional ML experiment: relative-strength features vs deployed v2 model.

Hypothesis: in crypto, cross-sectional momentum (relative strength vs BTC and rank
among the universe) carries more signal than absolute technical features. The deployed
model (catboost_price_dir_v2.cbm) reaches prob_up>=0.65 on only 0.26% of bars, making
the live entry gate almost unreachable. This experiment tests whether adding
cross-sectional features produces a model with higher AUC and/or higher hit rate at
reachable thresholds, on a strict per-symbol walk-forward split (70/30, gap 48).

No production files are touched; output is a report + optional candidate model file.

Usage:
    python scripts/quant_ml_cross_sectional.py [--output data/reports/ml_cross_sectional.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # sibling ml modules (quant_ml_eval_train)
sys.path.insert(0, str(HERE.parent / "research"))  # quant_monthly_backtest

import quant_monthly_backtest as qmb  # noqa: E402
from quant_ml_eval_train import GAP_BARS, NEW_FEATURES, TRAIN_FRAC, _metrics  # noqa: E402

BASE_FEATURES = NEW_FEATURES  # 13 scale-free features of the deployed v2 model

CROSS_FEATURES = [*BASE_FEATURES,
    "btc_ret6",        # BTC 6h return (market context)
    "btc_ret24",       # BTC 24h return
    "btc_regime",      # BTC close > SMA200
    "rel_ret6",        # symbol ret6 - btc_ret6 (alpha vs market)
    "rel_ret24",       # symbol ret24 - btc_ret24
    "mom_rank24",      # cross-sectional percentile rank of ret24 (0..1)
    "mom_rank6",       # cross-sectional percentile rank of ret6
    "vol_rank",        # cross-sectional percentile rank of ATR14/close
]


def build_panel() -> pd.DataFrame:
    """One row per (symbol, hour): base features + BTC context + cross-sectional ranks."""
    symbols, _venue = qmb.load_symbols("allowlist")
    frames = []
    for sym, df in symbols.items():
        g = qmb._compute_features(df).copy()
        g["ts_h"] = (g["timestamp_ms"] // 3_600_000).astype(np.int64)
        g["symbol"] = sym
        g["atr14"] = (g["high"] - g["low"]) / g["close"].replace(0, np.nan)
        frames.append(g[["ts_h", "symbol", "close", "vol_ratio", "atr14", *BASE_FEATURES]])
    panel = pd.concat(frames, ignore_index=True)

    # BTC context (dedup ts_h: live collector may append duplicate bars)
    btc = panel[panel["symbol"] == "BTC"].set_index("ts_h")
    btc = btc[~btc.index.duplicated(keep="last")]
    btc_close = btc["close"]
    btc_ret6 = btc["ret6"]
    btc_ret24 = btc["ret24"]
    btc_sma200 = btc_close.rolling(200).mean()
    btc_regime = (btc_close > btc_sma200).astype(float)

    panel["btc_ret6"] = panel["ts_h"].map(btc_ret6)
    panel["btc_ret24"] = panel["ts_h"].map(btc_ret24)
    panel["btc_regime"] = panel["ts_h"].map(btc_regime)
    panel["rel_ret6"] = panel["ret6"] - panel["btc_ret6"]
    panel["rel_ret24"] = panel["ret24"] - panel["btc_ret24"]

    # Cross-sectional ranks per hour
    panel["mom_rank24"] = panel.groupby("ts_h")["ret24"].rank(pct=True)
    panel["mom_rank6"] = panel.groupby("ts_h")["ret6"].rank(pct=True)
    panel["vol_rank"] = panel.groupby("ts_h")["atr14"].rank(pct=True)

    # Target: next 1h close direction
    panel = panel.sort_values(["symbol", "ts_h"]).reset_index(drop=True)
    panel["target"] = panel.groupby("symbol")["close"].shift(-1) > panel["close"]
    panel["target"] = panel["target"].astype(int)
    return panel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=Path("data/reports/ml_cross_sectional.md"))
    args = ap.parse_args()

    panel = build_panel()
    print(f"panel rows: {len(panel)}, symbols: {panel['symbol'].nunique()}", flush=True)

    rows = []
    for sym, g in panel.groupby("symbol"):
        g = g.dropna(subset=[*BASE_FEATURES, "target"]).reset_index(drop=True)
        if len(g) < 1500:
            continue
        cut = int(len(g) * TRAIN_FRAC)
        rows.append((sym, g.iloc[: cut - GAP_BARS], g.iloc[cut:]))
    print(f"symbols admitted: {len(rows)}", flush=True)

    df_train = pd.concat([tr for _, tr, _ in rows], ignore_index=True)
    df_test = pd.concat([te for _, _, te in rows], ignore_index=True)
    print(f"train rows={len(df_train)} test rows={len(df_test)}", flush=True)

    from catboost import CatBoostClassifier

    results = {}

    # 1) Deployed model baseline on the same test window (base features)
    deployed = CatBoostClassifier()
    deployed.load_model(str(qmb.MODELS_DIR / "catboost_price_dir_v2.cbm"))
    results["deployed_v2"] = _eval(deployed, df_test, BASE_FEATURES)
    print("deployed_v2:", json.dumps(results["deployed_v2"], ensure_ascii=False), flush=True)

    # 2) Candidate: same hyperparams, base features only (control for training data)
    cand_base = CatBoostClassifier(iterations=400, depth=5, learning_rate=0.03,
                                   l2_leaf_reg=5.0, loss_function="Logloss",
                                   eval_metric="AUC", random_seed=42, verbose=0,
                                   thread_count=-1)
    cand_base.fit(df_train[BASE_FEATURES].values.astype(np.float64),
                  df_train["target"].values.astype(int))
    results["cand_base_only"] = _eval(cand_base, df_test, BASE_FEATURES)
    print("cand_base_only:", json.dumps(results["cand_base_only"], ensure_ascii=False), flush=True)

    # 3) Candidate: cross-sectional features
    cs_feats = [f for f in CROSS_FEATURES if f in df_train.columns]
    cand_cs = CatBoostClassifier(iterations=400, depth=5, learning_rate=0.03,
                                 l2_leaf_reg=5.0, loss_function="Logloss",
                                 eval_metric="AUC", random_seed=42, verbose=0,
                                 thread_count=-1)
    cand_cs.fit(df_train[cs_feats].values.astype(np.float64),
                df_train["target"].values.astype(int))
    results["cand_cross"] = _eval(cand_cs, df_test, cs_feats)
    print("cand_cross:", json.dumps(results["cand_cross"], ensure_ascii=False), flush=True)

    # 4) Feature importance (cross model)
    imp = sorted(zip(cs_feats, cand_cs.feature_importances_, strict=False), key=lambda x: -x[1])
    print("top features:", [(f, round(v, 1)) for f, v in imp[:12]], flush=True)

    md = ["# Cross-sectional ML эксперимент (относительная сила + ранги)", "",
          f"Сплит: per-symbol 70/30 gap {GAP_BARS}, train rows={len(df_train):,}, "
          f"test rows={len(df_test):,}. Гиперпараметры = v2 (400/depth5/lr0.03).",
          "",
          "| Модель | AUC | hit@0.55 | cov@0.55 | hit@0.65 | cov@0.65 |",
          "|---|---:|---:|---:|---:|---:|"]
    for name in ("deployed_v2", "cand_base_only", "cand_cross"):
        r = results[name]
        md.append(f"| {name} | {r['auc']:.4f} | {r.get('hit_055', 0):.3f} | "
                  f"{r.get('cov_055', 0):.4f} | {r.get('hit_065', 0):.3f} | "
                  f"{r.get('cov_065', 0):.4f} |")
    md += ["", "## Топ-фичи (cross-sectional модель)", ""]
    for f, v in imp[:12]:
        md.append(f"- {f}: {v:.1f}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {args.output}", flush=True)
    return 0


def _eval(model, df_test, features):
    X = df_test[features].values.astype(np.float64)
    prob = model.predict_proba(X)[:, 1]
    out = _metrics(df_test["target"].values.astype(int), np.asarray(prob, dtype=np.float64))
    # add 0.55 threshold (reachable by the deployed model)
    mask = prob >= 0.55
    out["cov_055"] = float(mask.mean())
    if mask.sum() > 0:
        out["hit_055"] = float(df_test["target"].values[mask].mean())
    return out


if __name__ == "__main__":
    raise SystemExit(main())
