#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""F-4: multi-horizon target experiment.

Does predicting direction H hours ahead (H=4, 24) beat the 1h target?
Hypothesis: longer horizons are less noisy, so a model trained on the h4/h24
target may be more informative for entries (engine still exits via TP/SL).

Honest per-symbol 70/30 gap 48 OOS, CatBoost v2 hyperparams, base 13 features.
AUC/hit/cov + engine PnL (1:1 live config) for the best horizon.

Usage:
    python scripts/quant_ml_horizon_experiment.py [--output data/reports/ml_horizon_experiment.md]
"""

from __future__ import annotations

import argparse
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
HORIZONS = {"h1": 1, "h4": 4, "h24": 24}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=Path("data/reports/ml_horizon_experiment.md"))
    args = ap.parse_args()

    env = load_unit_env()
    cfg = build_config(env)

    symbols, _venue = qmb.load_symbols("allowlist")
    frames = []
    for sym, df in symbols.items():
        g = qmb._compute_features(df).copy()
        g["symbol"] = sym
        frames.append(g)
    panel = pd.concat(frames, ignore_index=True)
    print(f"panel rows={len(panel)} symbols={panel['symbol'].nunique()}", flush=True)

    from catboost import CatBoostClassifier

    results = {}
    for name, h in HORIZONS.items():
        # target: close moves UP over the next h bars (h>=1)
        panel[f"target_{name}"] = (
            panel.groupby("symbol")["close"].shift(-h) > panel["close"]
        ).astype(int)
        rows = []
        for sym, g in panel.groupby("symbol"):
            g = g.dropna(subset=[*BASE_FEATURES, f"target_{name}"]).reset_index(drop=True)
            if len(g) < 1500:
                continue
            cut = int(len(g) * 0.70)
            rows.append((sym, g.iloc[: cut - GAP_BARS], g.iloc[cut:]))
        df_train = pd.concat([tr for _, tr, _ in rows], ignore_index=True)
        df_test = pd.concat([te for _, _, te in rows], ignore_index=True)

        m = CatBoostClassifier(iterations=400, depth=5, learning_rate=0.03,
                               l2_leaf_reg=5.0, loss_function="Logloss",
                               eval_metric="AUC", random_seed=42, verbose=0, thread_count=-1)
        m.fit(df_train[BASE_FEATURES].values.astype(np.float64),
              df_train[f"target_{name}"].values.astype(int))
        p = m.predict_proba(df_test[BASE_FEATURES].values.astype(np.float64))[:, 1]
        r = _metrics(df_test[f"target_{name}"].values.astype(int), np.asarray(p, dtype=np.float64))
        for thr in (0.55, 0.60, 0.65):
            mask = p >= thr
            r[f"cov_{int(thr*100):03d}"] = float(mask.mean())
            if mask.sum() > 0:
                r[f"hit_{int(thr*100):03d}"] = float(df_test[f"target_{name}"].values[mask].mean())
        print(f"{name}: auc={r['auc']:.4f} up_rate={r['up_rate']:.3f} "
              f"hit55={r.get('hit_055',0):.3f} cov55={r.get('cov_055',0):.4f}", flush=True)
        results[name] = (r, m)

    # engine PnL: deployed (h1 prod) vs h4 model vs h24 model on the same OOS window
    from quant_tf_universe_experiment import build_series

    s1h = build_series(env, None, "1h")
    t0 = min(int(si["times"][int(len(si["times"]) * 0.70)]) for si in s1h.values())
    dep = CatBoostClassifier()
    dep.load_model(str(qmb.MODELS_DIR / "catboost_price_dir_v2.cbm"))
    pnl_rows = []
    for label, model in (("deployed_v2(h1)", dep), ("h4_model", results["h4"][1]),
                         ("h24_model", results["h24"][1])):
        probs = {}
        for key, s in s1h.items():
            X = s["feats"][BASE_FEATURES].values.astype(np.float64)
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

    md = ["# F-4: multi-horizon target эксперимент (h1/h4/h24)", "",
          f"OOS: {d0} .. {d1} | сплит 70/30 gap {GAP_BARS} | base 13 фич | CatBoost v2",
          "",
          "| Горизонт | AUC | up_rate | hit@0.55 | cov@0.55 | hit@0.60 |",
          "|---|---:|---:|---:|---:|---:|"]
    for name in HORIZONS:
        r = results[name][0]
        md.append(f"| {name} | {r['auc']:.4f} | {r['up_rate']:.3f} | "
                  f"{fnum(r.get('hit_055',0))} | {fnum(r.get('cov_055',0),4)} | "
                  f"{fnum(r.get('hit_060',0))} |")
    md += ["", "| Модель (PnL движок) | Сделок | WR | PF | PnL $ |",
           "|---|---:|---:|---:|---:|"]
    for label, m in pnl_rows:
        pf = fnum(m["pf"], 2)
        md.append(f"| {label} | {m['n']} | {m['wr']:.1f}% | {pf} | {m['pnl']:+.2f} |")
    md += ["", "## Вывод",
           "",
           "Правило: гипотеза жива, только если AUC(h4/h24) > AUC(h1)+0.005 И PnL > 0."]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
