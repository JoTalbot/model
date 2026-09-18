#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""F-2: funding-rate features experiment (new data class, Binance Futures).

Funding rate (8h intervals, public API) is merged onto 1h bars WITHOUT lookahead:
for bar t only funding with fundingTime <= t is used (ffill), aggregates over
closed funding periods only.

Features (per symbol):
  f_last, f_24h_sum, f_7d_sum, f_7d_std, f_neg_frac7, f_30d_z, f_sign, f_extreme

Models: CatBoost v2 hyperparams; honest per-symbol 70/30 gap 48 OOS (~5 months
train / ~2.2 months test on 166 days of funding). PnL via the 1:1 engine replica
(live config). Baseline: base 13 features only.

Usage:
    python scripts/quant_ml_funding_experiment.py [--output data/reports/ml_funding_experiment.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # sibling ml modules (quant_ml_eval_train)
sys.path.insert(0, str(HERE.parent / "research"))  # quant_monthly_backtest

import quant_monthly_backtest as qmb  # noqa: E402
from quant_ml_eval_train import GAP_BARS, _metrics  # noqa: E402
from quant_prod_3m_backtest import build_config, load_unit_env, run_backtest, summarize  # noqa: E402

BASE_FEATURES = qmb.FEATURES
FUNDING_DIR = qmb.QUANT_DIR / "funding_oi"

FUNDING_FEATURES = [
    "f_last", "f_24h_sum", "f_7d_sum", "f_7d_std", "f_neg_frac7", "f_30d_z", "f_sign", "f_extreme",
]


def load_funding(sym: str) -> pd.DataFrame:
    p = FUNDING_DIR / f"{sym}_funding.json"
    if not p.exists():
        return pd.DataFrame(columns=["fundingTime", "fundingRate"])
    rows = json.loads(p.read_text())
    df = pd.DataFrame(rows)
    df["fundingTime"] = df["fundingTime"].astype(np.int64)
    df["fundingRate"] = df["fundingRate"].astype(float)
    return df.sort_values("fundingTime")


def add_funding_features(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Merge funding onto 1h bars (closed funding periods only, no lookahead).

    Vectorized with merge_asof: aggregates are computed on the 8h funding grid,
    then the LAST KNOWN value (fundingTime <= bar time) is attached to each bar.
    """
    g = df.copy()
    f = load_funding(sym)
    if f.empty:
        for c in FUNDING_FEATURES:
            g[c] = np.nan
        return g

    fr = pd.DataFrame({
        "fundingTime": f["fundingTime"].values,
        "rate": f["fundingRate"].values,
    }).sort_values("fundingTime")
    fr = fr[~fr["fundingTime"].duplicated(keep="last")].reset_index(drop=True)

    r = fr["rate"]
    fr["f_last"] = r
    fr["f_24h_sum"] = r.rolling(3, min_periods=1).sum()   # last 3 funding (24h)
    fr["f_7d_sum"] = r.rolling(21, min_periods=1).sum()   # 21 funding (7d)
    fr["f_7d_std"] = r.rolling(21, min_periods=2).std()
    fr["f_neg_frac7"] = (r < 0).astype(float).rolling(21, min_periods=1).mean()
    fr["f_30d_mean"] = r.rolling(90, min_periods=10).mean()
    fr["f_30d_std"] = r.rolling(90, min_periods=10).std()
    fr["f_30d_p95_abs"] = r.abs().rolling(90, min_periods=10).quantile(0.95)
    fr["f_30d_z"] = (fr["f_last"] - fr["f_30d_mean"]) / fr["f_30d_std"].replace(0, np.nan)
    fr["f_extreme"] = (r.abs() > fr["f_30d_p95_abs"]).astype(float)

    bars = g[["timestamp_ms"]].copy().sort_values("timestamp_ms")
    merged = pd.merge_asof(bars, fr[["fundingTime", "f_last", "f_24h_sum", "f_7d_sum",
                                     "f_7d_std", "f_neg_frac7", "f_30d_z", "f_extreme"]],
                           left_on="timestamp_ms", right_on="fundingTime",
                           direction="backward")
    merged = merged.set_index("timestamp_ms")
    merged["f_sign"] = np.sign(merged["f_last"])
    for c in FUNDING_FEATURES:
        g[c] = merged[c].values
    return g


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=Path("data/reports/ml_funding_experiment.md"))
    args = ap.parse_args()

    env = load_unit_env()
    cfg = build_config(env)

    symbols, _venue = qmb.load_symbols("allowlist")
    frames = []
    for sym, df in symbols.items():
        g = qmb._compute_features(df).copy()
        g["symbol"] = sym
        g = add_funding_features(g, sym)
        frames.append(g)
    panel = pd.concat(frames, ignore_index=True)
    panel["target"] = panel.groupby("symbol")["close"].shift(-1) > panel["close"]
    panel["target"] = panel["target"].astype(int)
    print(f"panel rows={len(panel)} symbols={panel['symbol'].nunique()}", flush=True)

    rows = []
    for sym, g in panel.groupby("symbol"):
        g = g.dropna(subset=[*BASE_FEATURES, "target"]).reset_index(drop=True)
        if len(g) < 1500:
            continue
        cut = int(len(g) * 0.70)
        rows.append((sym, g.iloc[: cut - GAP_BARS], g.iloc[cut:]))
    df_train = pd.concat([tr for _, tr, _ in rows], ignore_index=True)
    df_test = pd.concat([te for _, _, te in rows], ignore_index=True)
    print(f"train rows={len(df_train)} test rows={len(df_test)}", flush=True)

    from catboost import CatBoostClassifier

    fcols = [c for c in FUNDING_FEATURES if c in df_train.columns]
    print(f"funding cols used: {fcols}", flush=True)

    def fit_eval(feats, name):
        m = CatBoostClassifier(iterations=400, depth=5, learning_rate=0.03,
                               l2_leaf_reg=5.0, loss_function="Logloss",
                               eval_metric="AUC", random_seed=42, verbose=0, thread_count=-1)
        m.fit(df_train[feats].values.astype(np.float64),
              df_train["target"].values.astype(int))
        X = df_test[feats].values.astype(np.float64)
        p = m.predict_proba(X)[:, 1]
        r = _metrics(df_test["target"].values.astype(int), np.asarray(p, dtype=np.float64))
        for thr in (0.55, 0.60, 0.65):
            mask = p >= thr
            r[f"cov_{int(thr*100):03d}"] = float(mask.mean())
            if mask.sum() > 0:
                r[f"hit_{int(thr*100):03d}"] = float(df_test["target"].values[mask].mean())
        print(f"{name}: auc={r['auc']:.4f} hit55={r.get('hit_055',0):.3f} "
              f"cov55={r.get('cov_055',0):.4f} hit60={r.get('hit_060',0):.3f} "
              f"cov60={r.get('cov_060',0):.4f}", flush=True)
        return r, m

    r_base, _m_base = fit_eval(BASE_FEATURES, "cand_base")
    r_fund, m_fund = fit_eval(BASE_FEATURES + fcols, "cand_funding")

    imp = sorted(zip(BASE_FEATURES + fcols, m_fund.feature_importances_, strict=False),
                 key=lambda x: -x[1])
    print("top features:", [(f, round(float(v), 1)) for f, v in imp[:14]], flush=True)

    # ---- engine PnL on the same OOS window ----
    from quant_tf_universe_experiment import build_series

    s1h = build_series(env, None, "1h")
    t0 = min(int(si["times"][int(len(si["times"]) * 0.70)]) for si in s1h.values())
    # deployed model (prod baseline) + funding model PnL
    dep = CatBoostClassifier()
    dep.load_model(str(qmb.MODELS_DIR / "catboost_price_dir_v2.cbm"))
    pnl_rows = []
    for label, model, feats in (("deployed_v2", dep, BASE_FEATURES),
                                ("funding_model", m_fund, BASE_FEATURES + fcols)):
        probs = {}
        for key, s in s1h.items():
            sym = s["symbol"]
            g = s["feats"].copy()
            g = add_funding_features(g, sym)
            X = g[feats].values.astype(np.float64)
            probs[key] = model.predict_proba(X)[:, 1]
            s["probs"] = probs[key]
        res = run_backtest(s1h, cfg, probs, t0)
        m = summarize(res, cfg)
        pf = m["pf"] if m["pf"] == float("inf") else round(m["pf"], 2)
        print(f"PnL {label}: n={m['n']} wr={m['wr']:.1f}% pf={pf} pnl={m['pnl']:+.2f}$", flush=True)
        pnl_rows.append((label, m))

    d0 = datetime.fromtimestamp(t0 / 1000, tz=UTC).strftime("%Y-%m-%d")
    d1 = datetime.fromtimestamp(max(int(si["times"][-1]) for si in s1h.values()) / 1000,
                                tz=UTC).strftime("%Y-%m-%d")

    def fnum(v, nd=3):
        return "inf" if v == float("inf") else f"{v:.{nd}f}"

    md = ["# F-2: funding-rate фичи — эксперимент (новый класс данных)", "",
          f"OOS-окно: {d0} .. {d1} (funding: 166 дней, 8h начисления) | "
          f"сплит 70/30 gap {GAP_BARS} | train {len(df_train):,} / test {len(df_test):,}",
          "",
          "Методика: funding без lookahead (только начисления с fundingTime <= t, ffill);",
          "фичи: f_last, f_24h_sum, f_7d_sum, f_7d_std, f_neg_frac7, f_30d_z, f_sign, f_extreme.",
          "Катбуст 400/5/0.03; PnL — движок 1:1 (live config).",
          "",
          "| Модель | AUC | hit@0.55 | cov@0.55 | hit@0.60 | cov@0.60 | Сделок | PnL $ |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, r in (("cand_base", r_base), ("cand_funding", r_fund)):
        md.append(f"| {name} | {r['auc']:.4f} | {fnum(r.get('hit_055',0))} | "
                  f"{fnum(r.get('cov_055',0),4)} | {fnum(r.get('hit_060',0))} | "
                  f"{fnum(r.get('cov_060',0),4)} | — | — |")
    for label, m in pnl_rows:
        pf = fnum(m["pf"], 2)
        md.append(f"| {label} (PnL) | — | — | — | — | — | {m['n']} | {m['pnl']:+.2f} |")
    md += ["", "## Топ-фичи funding-модели", ""]
    for f, v in imp[:14]:
        md.append(f"- {f}: {v:.1f}")
    md += ["", "## Вывод",
           "",
           "Правило решения: гипотеза жива, только если AUC(funding) > AUC(base) + 0.005 "
           "И PnL(funding) > 0. Иначе — funding rate на 8h-начислениях не несёт edge "
           "для 1h-направления после издержек."]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
