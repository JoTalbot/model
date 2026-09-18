#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""Triple-barrier label experiment for the Directional-v2 ML model.

Hypothesis (Edge Lab 2026-08-17): the deployed model's AUC 0.533 may be an
artifact of the noisy next-bar direction label. This experiment labels bars
with the engine's own barriers — TP +2% / SL -1% (intrabar high/low, first
touch wins), vertical timeout 24h (sign of close at timeout) — trains the
SAME CatBoost v2 on the SAME 13 scale-free features, and compares honestly:

- purge split: train observations must CLOSE their label before the test
  window starts (no leakage through the barrier);
- test = last 30% of bars;
- metrics: AUC, hit@0.65, cov@0.65, plus an engine-style simulation
  (long when prob >= q90(train), barrier exits, 0.5% round-trip cost)
  for both label schemes on the same split.

Read-only research; writes data/reports/triple_barrier_report.md.

Usage:
    python scripts/quant_ml_triple_barrier.py [--symbols auto] [--out ...]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from swarm.quant.ml_predictor import DEFAULT_FEATURES

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_DIR = REPO_ROOT / "data" / "quant"

TP_PCT = 0.02
SL_PCT = 0.01
TIMEOUT_BARS = 24
COST = 0.005  # engine round trip: 200*(fee 0.0015 + spread 0.0005 + slip 0.0005)



def _features_df(g: pd.DataFrame) -> pd.DataFrame:
    """Vectorized copy of QuantMLPredictor formulas (1:1 with training)."""

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
    return f


def triple_barrier_labels(high: np.ndarray, low: np.ndarray,
                          close: np.ndarray, *,
                          tp: float = TP_PCT, sl: float = SL_PCT,
                          timeout: int = TIMEOUT_BARS) -> tuple[np.ndarray, np.ndarray]:
    """Labels: 1 when TP touched first, 0 when SL first, else sign of the
    timeout close. Also returns the bar offset where the label closes
    (needed for the purge split)."""

    n = len(close)
    y = np.zeros(n, dtype=int)
    close_at = np.full(n, -1, dtype=int)
    for i in range(n):
        c = close[i]
        up_lvl = c * (1 + tp)
        dn_lvl = c * (1 - sl)
        j = i + 1
        label = -1
        while j < n:
            # оба барьера в одном баре -> консервативно SL (порядок касаний
            # из OHLC не восстановим); иначе первый достигнутый решает
            if high[j] >= up_lvl and low[j] <= dn_lvl:
                label = 0
                break
            if high[j] >= up_lvl:
                label = 1
                break
            if low[j] <= dn_lvl:
                label = 0
                break
            if j - i >= timeout:
                label = 1 if close[j] > c else 0
                break
            j += 1
        if label == -1:
            # ran out of data before any barrier: use last close sign
            label = 1 if close[-1] > c else 0
            j = n - 1
        y[i] = label
        close_at[i] = j
    return y, close_at


def next_bar_labels(close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y = (close[1:] > close[:-1]).astype(int)
    close_at = np.arange(1, len(close))
    return y, close_at


def _fit_predict(X_tr, y_tr, X_te) -> np.ndarray:
    from catboost import CatBoostClassifier

    model = CatBoostClassifier(iterations=400, depth=5, learning_rate=0.03,
                               l2_leaf_reg=5.0, loss_function="Logloss",
                               eval_metric="AUC", random_seed=42, verbose=0,
                               thread_count=-1)
    model.fit(X_tr, y_tr.astype(int))
    return model.predict_proba(X_te)[:, 1]


def barrier_sim(probs: np.ndarray, thr: float, high: np.ndarray,
                low: np.ndarray, close: np.ndarray,
                *,
                tp: float = TP_PCT, sl: float = SL_PCT,
                timeout: int = TIMEOUT_BARS) -> dict:
    """Long when prob >= thr; exits on barriers; net of round-trip cost."""

    rets = []
    for i in np.nonzero(probs >= thr)[0]:
        c = close[i]
        up_lvl = c * (1 + tp)
        dn_lvl = c * (1 - sl)
        j = i + 1
        r = None
        while j < len(close):
            if high[j] >= up_lvl:
                r = tp
                break
            if low[j] <= dn_lvl:
                r = -sl
                break
            if j - i >= timeout:
                r = close[j] / c - 1.0
                break
            j += 1
        if r is None:
            r = close[-1] / c - 1.0
        rets.append(r - COST)
    rets = np.asarray(rets) if rets else np.array([0.0])
    return {
        "n": len(rets),
        "mean_pct": round(float(rets.mean()) * 100, 3),
        "positive_pct": round(float((rets > 0).mean()) * 100, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="auto",
                    help="auto = all symbols with binance 1h csv")
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "data" / "reports" / "triple_barrier_report.md")
    args = ap.parse_args()

    if args.symbols == "auto":
        symbols = sorted(p.parent.parent.name for p in
                         QUANT_DIR.glob("*/binance/*_1h.csv"))
    else:
        symbols = args.symbols.split(",")

    from sklearn.metrics import roc_auc_score

    rows: list[dict] = []
    for symbol in symbols:
        csv_paths = sorted(QUANT_DIR.glob(f"{symbol}/binance/{symbol}_1h.csv"))
        if not csv_paths:
            continue
        df = pd.read_csv(csv_paths[0]).sort_values("timestamp_ms").reset_index(drop=True)
        if len(df) < 400:
            continue
        f = _features_df(df)
        clean = f.dropna(subset=DEFAULT_FEATURES).reset_index(drop=True)
        # align original OHLC to the cleaned frame
        idx = f.dropna(subset=DEFAULT_FEATURES).index
        high = df["high"].values[idx]
        low = df["low"].values[idx]
        close = df["close"].values[idx]
        X = clean[DEFAULT_FEATURES].values.astype(np.float64)
        n = len(clean)

        tb_y, tb_close = triple_barrier_labels(high, low, close)
        nb_y, nb_close = next_bar_labels(close)

        split = int(n * 0.70)
        split_ts_idx = split
        # purge: train bars whose label closes after the split are excluded
        tb_tr = np.nonzero(tb_close < split_ts_idx)[0]
        tb_te = np.arange(split_ts_idx, n)
        nb_tr = np.nonzero(nb_close < split_ts_idx)[0]
        nb_te = np.arange(split_ts_idx, n - 1)
        if len(tb_tr) < 300 or len(tb_te) < 100:
            continue

        p_tb = _fit_predict(X[tb_tr], tb_y[tb_tr], X[tb_te])
        p_nb = _fit_predict(X[nb_tr], nb_y[nb_tr], X[nb_te])

        auc_tb = float(roc_auc_score(tb_y[tb_te], p_tb))
        auc_nb = float(roc_auc_score(nb_y[nb_te], p_nb))
        hit_tb = float(tb_y[tb_te][p_tb >= 0.65].mean()) if (p_tb >= 0.65).any() else float("nan")
        hit_nb = float(nb_y[nb_te][p_nb >= 0.65].mean()) if (p_nb >= 0.65).any() else float("nan")
        cov_tb = float((p_tb >= 0.65).mean())
        cov_nb = float((p_nb >= 0.65).mean())

        thr_tb = float(np.quantile(_fit_predict(X[tb_tr], tb_y[tb_tr], X[tb_tr]), 0.90))
        thr_nb = float(np.quantile(_fit_predict(X[nb_tr], nb_y[nb_tr], X[nb_tr]), 0.90))
        sim_tb = barrier_sim(p_tb, thr_tb, high[tb_te], low[tb_te], close[tb_te])
        sim_nb = barrier_sim(p_nb, thr_nb, high[nb_te], low[nb_te], close[nb_te])

        rows.append({
            "symbol": symbol,
            "n_train_tb": len(tb_tr), "n_test": len(tb_te),
            "auc_tb": round(auc_tb, 3), "auc_nb": round(auc_nb, 3),
            "hit065_tb": round(hit_tb, 3) if hit_tb == hit_tb else None,
            "hit065_nb": round(hit_nb, 3) if hit_nb == hit_nb else None,
            "cov065_tb": round(cov_tb, 4), "cov065_nb": round(cov_nb, 4),
            "sim_tb": sim_tb, "sim_nb": sim_nb,
        })
        print(f"{symbol}: AUC tb={auc_tb:.3f} nb={auc_nb:.3f} | hit tb={hit_tb} nb={hit_nb} "
              f"| sim tb={sim_tb['mean_pct']:+.2f}% (n={sim_tb['n']}) nb={sim_nb['mean_pct']:+.2f}% (n={sim_nb['n']})",
              flush=True)

    # aggregate
    auc_tb = np.array([r["auc_tb"] for r in rows])
    auc_nb = np.array([r["auc_nb"] for r in rows])
    lines = [
        "# Triple-barrier vs next-bar метки для ML Directional v2 (Edge Lab 2026-08-17)",
        "",
        "TP +2% / SL −1% / таймаут 24ч; purge-сплит 70/30; те же 13 фич и гиперпараметры; "
        "симуляция: long при prob≥q90(train), барьерные выходы, издержки 0.5%/round-trip.",
        "",
        f"Символов: {len(rows)}",
        f"Средний AUC: triple-barrier **{auc_tb.mean():.3f}** vs next-bar **{auc_nb.mean():.3f}**",
        f"Медиана AUC: tb {np.median(auc_tb):.3f} vs nb {np.median(auc_nb):.3f}",
        "",
        "| Символ | AUC tb | AUC nb | hit@0.65 tb | hit@0.65 nb | sim tb | sim nb |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['symbol']} | {r['auc_tb']:.3f} | {r['auc_nb']:.3f} "
            f"| {r['hit065_tb']} | {r['hit065_nb']} "
            f"| {r['sim_tb']['mean_pct']:+.2f}% ({r['sim_tb']['n']}) "
            f"| {r['sim_nb']['mean_pct']:+.2f}% ({r['sim_nb']['n']}) |"
        )
    lines += ["", "Вывод: см. docs/EDGE_LAB_TRIPLE_BARRIER_2026-08-17_RU.md (генерируется по результату)."]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
