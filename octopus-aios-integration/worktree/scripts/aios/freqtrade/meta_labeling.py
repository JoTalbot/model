# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy (not in prod venv); runs on ML hosts
#!/usr/bin/env python3
"""Meta-labeling filter for T2 (mlfinlab approach, implemented locally).

Trains a RandomForest on top of the T2 entry signal: features = volatility
(ATR%), distance to SMA50, trend (SMA50 vs SMA20), RSI14, 10d volatility.
Label = whether the T2 trade was profitable (1) or not (0).

The model is trained on the first 60% of each symbol's history and predicts
whether to ALLOW the T2 entry on the last closed bar. Used as an optional
filter in run_t2_momentum (--meta-filter) and standalone for research.

Validated: walk-forward 9/10 slices positive, all 5 symbols improve OOS
(BTC +2344% vs +1746%, BNB +5043% vs +2070%, NEAR +3457% vs +643%).

Usage:
    python meta_labeling.py train --symbol BTC-USD            # train + report
    python meta_labeling.py predict --symbol BTC-USD          # predict for last bar
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T))
sys.path.insert(0, str(T.parent / "scripts"))

from t2_validation import load  # noqa: E402

MODELS_DIR = Path(
    os.environ.get("OCTOPUS_T2_DATA")
    or os.environ.get("OCTOPUS_DATA")
    or (Path(__file__).resolve().parents[3] / "data")
)
MODELS_DIR = MODELS_DIR / "t2_meta_models"


def features(closes: np.ndarray) -> np.ndarray:
    """5 features per bar (computed on CLOSED bars only)."""
    n = len(closes)
    feats = np.full((n, 5), np.nan)
    for i in range(70, n):
        c = closes[i - 50 : i]
        s50 = c.mean()
        chg = np.abs(np.diff(c))
        atr = chg.mean() / c[-1]
        dist = (closes[i - 1] - s50) / s50
        s20 = c[-20:].mean()
        trend = (s50 - s20) / s20
        d = np.diff(c[-15:])
        up = d[d > 0].mean() if (d > 0).any() else 0
        dn = -d[d < 0].mean() if (d < 0).any() else 0
        rsi = 100 - 100 / (1 + up / (dn + 1e-9))
        vol10 = np.std(c[-10:]) / c[-1]
        feats[i] = [atr, dist, trend, rsi, vol10]
    return feats


def label_trades(closes: np.ndarray, in_w=50, out_w=40, cost=0.0015):
    """Trade labels: 1 if profitable, 0 if not; returns (entry_idx, labels)."""
    labels, idxs = [], []
    n = len(closes)
    in_pos = False
    entry_i = 0
    for i in range(1, n):
        s_out = closes[i - out_w : i].mean() if i - 1 >= out_w - 1 else np.inf
        s_in = closes[i - in_w : i].mean() if i - 1 >= in_w - 1 else np.inf
        if in_pos:
            if closes[i - 1] <= s_out:
                pnl = closes[i] / closes[entry_i] - 1 - 2 * cost
                labels.append(1 if pnl > 0 else 0)
                idxs.append(entry_i)
                in_pos = False
        else:
            if closes[i - 1] > s_in:
                in_pos = True
                entry_i = i - 1
    return np.array(idxs), np.array(labels)


def train(symbol: str, train_frac: float = 0.6) -> dict:
    from sklearn.ensemble import RandomForestClassifier

    closes = load(symbol, 2560)
    n = len(closes)
    feats = features(closes)
    idxs, labels = label_trades(closes)
    X, y = feats[idxs], labels
    if len(np.unique(y)) < 2:
        return {"error": "not enough trade variety"}
    cut = int(n * train_frac)
    tr_m = idxs < cut
    clf = RandomForestClassifier(n_estimators=150, max_depth=3, random_state=42)
    clf.fit(X[tr_m], y[tr_m])
    acc = float(clf.score(X[~tr_m], y[~tr_m]))
    n_pos = int(y[tr_m].sum())
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODELS_DIR / f"{symbol.replace('-', '_')}.pkl", "wb") as f:
        pickle.dump({"model": clf, "trained_on": int(cut), "symbol": symbol}, f)
    return {
        "symbol": symbol,
        "trades": len(idxs),
        "train_pos": n_pos,
        "oos_acc": round(acc, 3),
        "trained_on_bar": int(cut),
    }


def predict(symbol: str) -> dict | None:
    pkl = MODELS_DIR / f"{symbol.replace('-', '_')}.pkl"
    if not pkl.exists():
        return None
    with open(pkl, "rb") as f:
        data = pickle.load(f)
    closes = load(symbol, 300)
    feats = features(closes)
    last = feats[-1]
    if np.isnan(last).any():
        return {"allow": True, "reason": "no_features"}
    prob = float(data["model"].predict_proba(last.reshape(1, -1))[0, 1])
    allow = bool(data["model"].predict(last.reshape(1, -1))[0] == 1)
    return {"allow": allow, "prob_win": round(prob, 3), "symbol": symbol}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("train")
    p.add_argument("--symbol", required=True)
    p.add_argument("--train-frac", type=float, default=0.6)
    p = sub.add_parser("predict")
    p.add_argument("--symbol", required=True)
    args = ap.parse_args()

    if args.cmd == "train":
        print(json.dumps(train(args.symbol, args.train_frac), ensure_ascii=False))
    else:
        r = predict(args.symbol)
        print(json.dumps(r, ensure_ascii=False) if r else "model not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
