#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""Multi-timeframe ML experiment (hypothesis F, stage 1).

Adds higher-timeframe features (4h/1d, computed ONLY from closed bars <= t, so no
lookahead) and intraday seasonality to the 13 base 1h features, then compares on an
honest per-symbol walk-forward split (70/30, gap 48):
- deployed v2 model (baseline, base features);
- fresh candidate, base features only (control);
- fresh candidate, base + MTF features (hypothesis);
- engine PnL simulation (1:1 live config, fold-0.70 OOS window) for each.

If AUC does not clearly beat ~0.545 AND PnL stays negative, the local-data
ML hypothesis is considered exhausted (external signals would be needed).

Usage:
    python scripts/quant_ml_mtf_experiment.py [--output data/reports/ml_mtf_experiment.md]
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

BASE_FEATURES = qmb.FEATURES  # 13 scale-free 1h features

MTF_FEATURES = [
    # --- 4h timeframe (closed 4h bars only) ---
    "ret4h_1",        # 4h close-to-close return (last closed 4h bar)
    "ret4h_6",        # 4h return over 6 closed 4h bars (~24h)
    "rsi4h",          # RSI on 4h closes
    "bb_pos4h",       # Bollinger position on 4h closes
    "dist_sma20_4h",  # (close - sma20_4h) / close
    # --- 1d timeframe (closed daily bars only) ---
    "ret_d1",         # daily close-to-close return
    "ret_d7",         # 7d return
    "dist_sma20_1d",  # (close - sma20_1d) / close
    "day_pos",        # position in the last CLOSED day's range
    "day_range_pct",  # last closed day range / close
    # --- intraday seasonality ---
    "hour_sin",
    "hour_cos",
    "dow",            # day of week 0..6
]


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    chg = series.diff()
    up = chg.clip(lower=0).rolling(period).mean()
    down = (-chg.clip(upper=0)).rolling(period).mean()
    rs = up / down.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def build_mtf_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Add MTF features to the panel (already sorted by symbol, ts_h; bars <= t only)."""
    g = panel.copy()
    # timestamps in hours; 4h bar id and day id
    g["ts_4h"] = g["ts_h"] // 4
    g["ts_d"] = g["ts_h"] // 24

    def _apply(df: pd.DataFrame) -> pd.DataFrame:
        sym = df.name if isinstance(df.name, str) else df.name[0]
        df = df.sort_values("ts_h").copy()

        # ---- 4h closed bars (last 4h bar that ended <= t is bar ts_4h(t)) ----
        # ONLY CLOSED 4h groups: for bar t we use the 4h group that ended BEFORE t
        # (group ts_4h-1). Using the group containing t would leak future bars of the
        # group (its last close belongs to a later hour).
        g4 = df.groupby("ts_4h").agg(
            close4h=("close", "last"),
            high4h=("high", "max"),
            low4h=("low", "min"),
        )
        g4["ret4h_1"] = g4["close4h"].pct_change()
        g4["ret4h_6"] = g4["close4h"].pct_change(6)
        g4["rsi4h"] = _rsi(g4["close4h"])
        sma20_4h = g4["close4h"].rolling(20).mean()
        bb_std = g4["close4h"].rolling(20).std()
        g4["bb_pos4h"] = ((g4["close4h"] - sma20_4h + 2 * bb_std) / (4 * bb_std).replace(0, np.nan)).clip(0, 1)
        g4["dist_sma20_4h"] = (g4["close4h"] - sma20_4h) / g4["close4h"].replace(0, np.nan)
        g4 = g4.shift(1)  # <-- closed groups only (no lookahead)
        df = df.merge(g4[["ret4h_1", "ret4h_6", "rsi4h", "bb_pos4h", "dist_sma20_4h"]],
                      left_on="ts_4h", right_index=True, how="left")

        # ---- 1d closed bars ----
        gd = df.groupby("ts_d").agg(
            close_d=("close", "last"),
            high_d=("high", "max"),
            low_d=("low", "min"),
        )
        gd["ret_d1"] = gd["close_d"].pct_change()
        gd["ret_d7"] = gd["close_d"].pct_change(7)
        sma20_d = gd["close_d"].rolling(20).mean()
        gd["dist_sma20_1d"] = (gd["close_d"] - sma20_d) / gd["close_d"].replace(0, np.nan)
        gd = gd.shift(1)  # <-- closed days only (no lookahead)
        df = df.merge(gd[["close_d", "high_d", "low_d", "ret_d1", "ret_d7", "dist_sma20_1d"]],
                      left_on="ts_d", right_index=True, how="left")
        # day_pos: current price within the LAST CLOSED day's range
        rng = (df["high_d"] - df["low_d"]).replace(0, np.nan)
        df["day_pos"] = ((df["close"] - df["low_d"]) / rng).clip(0, 1)
        df["day_range_pct"] = rng / df["close"].replace(0, np.nan)

        # ---- intraday seasonality ----
        hh = (df["ts_h"] % 24).astype(int)
        df["hour_sin"] = np.sin(2 * np.pi * hh / 24)
        df["hour_cos"] = np.cos(2 * np.pi * hh / 24)
        df["dow"] = (pd.to_datetime(df["ts_h"] * 3_600_000, unit="ms", utc=True).dt.dayofweek).astype(int)
        df["symbol"] = sym
        return df

    return g.groupby("symbol", group_keys=False).apply(_apply).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=Path("data/reports/ml_mtf_experiment.md"))
    args = ap.parse_args()

    env = load_unit_env()
    cfg = build_config(env)

    # Build panel (same as cross-sectional script): 1h bars for all allowlist symbols
    symbols, _venue = qmb.load_symbols("allowlist")
    frames = []
    for sym, df in symbols.items():
        g = qmb._compute_features(df).copy()
        g["ts_h"] = (g["timestamp_ms"] // 3_600_000).astype(np.int64)
        g["symbol"] = sym
        frames.append(g[["ts_h", "symbol", "timestamp_ms", "open", "high", "low", "close",
                         "volume", *BASE_FEATURES]])
    panel = pd.concat(frames, ignore_index=True)
    panel["target"] = panel.groupby("symbol")["close"].shift(-1) > panel["close"]
    panel["target"] = panel["target"].astype(int)

    panel = build_mtf_features(panel)
    print(f"panel rows={len(panel)} symbols={panel['symbol'].nunique()}", flush=True)

    # per-symbol split
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

    mtf_cols = [c for c in MTF_FEATURES if c in df_train.columns]

    def fit_eval(feats: list[str], name: str) -> dict:
        m = CatBoostClassifier(iterations=400, depth=5, learning_rate=0.03,
                               l2_leaf_reg=5.0, loss_function="Logloss",
                               eval_metric="AUC", random_seed=42, verbose=0, thread_count=-1)
        m.fit(df_train[feats].values.astype(np.float64), df_train["target"].values.astype(int))
        X = df_test[feats].values.astype(np.float64)
        p = m.predict_proba(X)[:, 1]
        r = _metrics(df_test["target"].values.astype(int), np.asarray(p, dtype=np.float64))
        for thr in (0.55, 0.60, 0.65):
            mask = p >= thr
            r[f"cov_{int(thr*100):03d}"] = float(mask.mean())
            if mask.sum() > 0:
                r[f"hit_{int(thr*100):03d}"] = float(df_test["target"].values[mask].mean())
        print(f"{name}: auc={r['auc']:.4f} hit55={r.get('hit_055',0):.3f} cov55={r.get('cov_055',0):.4f} "
              f"hit65={r.get('hit_065',0):.3f} cov65={r.get('cov_065',0):.4f}", flush=True)
        return r, m

    # deployed baseline
    dep = CatBoostClassifier()
    dep.load_model(str(qmb.MODELS_DIR / "catboost_price_dir_v2.cbm"))
    X = df_test[BASE_FEATURES].values.astype(np.float64)
    p_dep = dep.predict_proba(X)[:, 1]
    r_dep = _metrics(df_test["target"].values.astype(int), np.asarray(p_dep, dtype=np.float64))
    for thr in (0.55, 0.60, 0.65):
        mask = p_dep >= thr
        r_dep[f"cov_{int(thr*100):03d}"] = float(mask.mean())
        if mask.sum() > 0:
            r_dep[f"hit_{int(thr*100):03d}"] = float(df_test["target"].values[mask].mean())
    print(f"deployed_v2: auc={r_dep['auc']:.4f} hit55={r_dep.get('hit_055',0):.3f} "
          f"cov55={r_dep.get('cov_055',0):.4f}", flush=True)

    r_base, _m_base = fit_eval(BASE_FEATURES, "cand_base")
    r_mtf, m_mtf = fit_eval(BASE_FEATURES + mtf_cols, "cand_mtf")

    # feature importance of MTF model
    imp = sorted(zip(BASE_FEATURES + mtf_cols, m_mtf.feature_importances_, strict=False), key=lambda x: -x[1])
    print("top features:", [(f, round(float(v), 1)) for f, v in imp[:14]], flush=True)

    # ---- engine PnL on the same OOS window (fold 0.70, live config) ----
    from quant_tf_universe_experiment import build_series

    s1h = build_series(env, None, "1h")
    # predict with MTF model? engine uses series probs; compute probs per series via mtf model
    # (simplify: use deployed model for PnL - consistent with live; MTF PnL needs panel
    #  alignment per series, done below via cand_mtf on the panel test rows)
    t0 = min(int(si["times"][int(len(si["times"]) * 0.70)]) for si in s1h.values())
    # deployed PnL
    probs_dep = {}
    for key, s in s1h.items():
        X = s["feats"][qmb.FEATURES].values.astype(np.float64)
        probs_dep[key] = dep.predict_proba(X)[:, 1]
        s["probs"] = probs_dep[key]
    res_dep = run_backtest(s1h, cfg, probs_dep, t0)
    m_dep = summarize(res_dep, cfg)
    print(f"PnL deployed: n={m_dep['n']} pnl={m_dep['pnl']:+.2f}$ wr={m_dep['wr']:.1f}% "
          f"pf={m_dep['pf'] if m_dep['pf']==float('inf') else round(m_dep['pf'],2)}", flush=True)

    # MTF PnL: map panel test rows back to series; predict probs per symbol on its own df
    # (reuse trained mtf model on per-symbol feature frames)
    probs_mtf = {}
    for key, s in s1h.items():
        sym = s["symbol"]
        feats = s["feats"].copy()
        feats["ts_h"] = (feats["timestamp_ms"] // 3_600_000).astype(np.int64)
        feats["symbol"] = sym
        tmp = build_mtf_features(feats)
        X = tmp[BASE_FEATURES + mtf_cols].values.astype(np.float64)
        p = m_mtf.predict_proba(X)[:, 1]
        s["probs"] = p
        probs_mtf[key] = p
    res_mtf = run_backtest(s1h, cfg, probs_mtf, t0)
    m_mtf_pnl = summarize(res_mtf, cfg)
    print(f"PnL MTF-model: n={m_mtf_pnl['n']} pnl={m_mtf_pnl['pnl']:+.2f}$ wr={m_mtf_pnl['wr']:.1f}% "
          f"pf={m_mtf_pnl['pf'] if m_mtf_pnl['pf']==float('inf') else round(m_mtf_pnl['pf'],2)}", flush=True)

    d0 = datetime.fromtimestamp(t0 / 1000, tz=UTC).strftime("%Y-%m-%d")
    d1 = datetime.fromtimestamp(max(int(si["times"][-1]) for si in s1h.values()) / 1000, tz=UTC).strftime("%Y-%m-%d")

    def fnum(v, nd=3):
        return "inf" if v == float("inf") else f"{v:.{nd}f}"

    md = ["# ML гипотеза F, этап 1: multi-timeframe фичи (4h/1d + сезонность)", "",
          f"OOS-окно: {d0} .. {d1} | Сплит: per-symbol 70/30 gap {GAP_BARS} | "
          f"train {len(df_train):,} / test {len(df_test):,}",
          "",
          "Методика: MTF-фичи только по ЗАКРЫТЫМ барам ≤ t (без lookahead); модели — CatBoost "
          "400/depth5/lr0.03 (те же гиперпараметры); PnL — движок 1:1 (live config: "
          f"trail={cfg.trail_ratio}, TP {cfg.take_profit_pct:.0%}, SL {cfg.stop_loss_pct:.0%}, "
          f"ML≥{cfg.ml_min_prob_up}).",
          "",
          "| Модель | AUC | hit@0.55 | cov@0.55 | hit@0.65 | cov@0.65 | Сделок | PnL $ |",
          "|---|---:|---:|---:|---:|---:|---:|---:|",
          f"| deployed v2 (base 13) | {r_dep['auc']:.4f} | {fnum(r_dep.get('hit_055',0))} | "
          f"{fnum(r_dep.get('cov_055',0),4)} | {fnum(r_dep.get('hit_065',0))} | "
          f"{fnum(r_dep.get('cov_065',0),4)} | {m_dep['n']} | {m_dep['pnl']:+.2f} |",
          f"| cand base-only (свежая) | {r_base['auc']:.4f} | {fnum(r_base.get('hit_055',0))} | "
          f"{fnum(r_base.get('cov_055',0),4)} | {fnum(r_base.get('hit_065',0))} | "
          f"{fnum(r_base.get('cov_065',0),4)} | — | — |",
          f"| cand MTF (base+{len(mtf_cols)}) | {r_mtf['auc']:.4f} | {fnum(r_mtf.get('hit_055',0))} | "
          f"{fnum(r_mtf.get('cov_055',0),4)} | {fnum(r_mtf.get('hit_065',0))} | "
          f"{fnum(r_mtf.get('cov_065',0),4)} | {m_mtf_pnl['n']} | {m_mtf_pnl['pnl']:+.2f} |",
          "",
          "## Топ-фичи MTF-модели", ""]
    for f, v in imp[:14]:
        md.append(f"- {f}: {v:.1f}")
    md += ["", "## Вывод",
           "",
           "- Если AUC(MTF) ≤ ~0.545 и PnL < 0 — гипотеза multi-timeframe на локальных данных "
           "не подтверждается; локальные данные исчерпаны, дальнейший прогресс требует "
           "внешних сигналов (funding/OI, новости, on-chain) с API-доступом.",
           "- Правило решения: только если AUC(MTF) > AUC(base)+0.005 И PnL(MTF) > 0 на этом "
           "OOS — гипотеза жива и требует следующего нетронутого окна."]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
