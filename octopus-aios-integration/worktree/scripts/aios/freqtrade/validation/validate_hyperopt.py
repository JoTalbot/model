#!/usr/bin/env python3
"""Validate hyperopt-found T2 windows vs baseline (full range + 2y OOS).

For each pair runs freqtrade backtests with:
  - baseline windows (50/40; BNB/NEAR 50/50)  -> T2Momentum
  - hyperopt best windows                       -> T2MomentumHyper + env T2_IN_W/T2_OUT_W
on the full range and on the last 730 days (out-of-sample-ish check).

Usage:
    python validate_hyperopt.py --best "BTC=56,56 ETH=50,50 ..." [same args as run_validation]
"""

import argparse
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FEE = "0.0015"
WINDOWS_BASELINE = {"BTC": (50, 40), "ETH": (50, 40), "SOL": (50, 40), "BNB": (50, 50), "NEAR": (50, 50)}
RANGE_FULL = "20190720-20260816"
RANGE_OOS = "20240817-20260816"  # last 730 days

ARGS = None


def _write_params(strategy: str, windows: tuple[int, int] | None):
    """freqtrade auto-loads '<strategy>.json' next to the strategy file and
    applies its params - use that (deterministic) instead of env hacks."""
    if windows is None:
        return
    module = {"T2Momentum": "freqtrade_t2", "T2MomentumHyper": "freqtrade_t2_hyper"}.get(strategy, strategy)
    p = ARGS.strategy_path / f"{module}.json"
    p.write_text(
        json.dumps(
            {
                "strategy_name": strategy,
                "params": {
                    "buy": {"in_w": windows[0]},
                    "sell": {"out_w": windows[1]},
                },
                "ft_stratparam_v": 1,
                "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            indent=2,
        )
    )


def run_bt(
    sym: str, strategy: str, windows: tuple[int, int] | None, timerange: str, extra_env: dict | None = None
) -> dict:
    cfg = ARGS.configs_dir / f"config_t2_{sym}.json"
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    _write_params(strategy, windows)
    cmd = [
        str(ARGS.freqtrade_bin),
        "backtesting",
        "--strategy",
        strategy,
        "--strategy-path",
        str(ARGS.strategy_path),
        "--config",
        str(cfg),
        "--datadir",
        str(ARGS.data_dir),
        "--timerange",
        timerange,
        "--fee",
        FEE,
        "--data-format-ohlcv",
        "json",
        "--userdir",
        str(ARGS.userdir),
        "--export",
        "trades",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"backtest failed {sym}/{strategy}/{timerange}: {(r.stdout + r.stderr)[-1500:]}")
    zips = sorted(ARGS.results_dir.glob("*.zip"))
    if not zips:
        raise RuntimeError("no results zip")
    with zipfile.ZipFile(zips[-1]) as zf:
        name = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n][0]  # noqa: RUF015
        data = json.loads(zf.read(name))
    st = data["strategy"][strategy]
    return {
        "trades": st["total_trades"],
        "profit": st["profit_total"] * 100,
        "maxdd": st["max_drawdown_account"] * 100,
        "sharpe": st["sharpe"],
        "sortino": st["sortino"],
        "winrate": st["winrate"],
    }


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--best", required=True, help="best windows per pair, e.g. 'BTC=56,56 ETH=50,40 ...'")
    ap.add_argument("--exchange", default="okx")
    ap.add_argument("--data-dir", default=str(HERE / "user_data" / "data" / "okx"))
    ap.add_argument("--configs-dir", default=str(HERE / "configs"))
    ap.add_argument("--results-dir", default=str(HERE / "user_data" / "backtest_results"))
    ap.add_argument("--userdir", default=str(HERE / "user_data"))
    ap.add_argument("--strategy-path", default=str(HERE / "strategies"))
    ap.add_argument("--freqtrade-bin", default="freqtrade")
    ap.add_argument("--pairs", default="BTC,ETH,SOL,BNB,NEAR")
    a = ap.parse_args()
    ARGS = argparse.Namespace(
        exchange=a.exchange,
        data_dir=Path(a.data_dir),
        configs_dir=Path(a.configs_dir),
        results_dir=Path(a.results_dir),
        userdir=Path(a.userdir),
        strategy_path=Path(a.strategy_path),
        freqtrade_bin=a.freqtrade_bin,
    )
    ARGS.results_dir.mkdir(parents=True, exist_ok=True)

    best = {}
    for tok in a.best.split():
        sym, w = tok.split("=")
        iw, ow = map(int, w.split(","))
        best[sym] = (iw, ow)

    hdr = (
        f"{'SYM':5s} {'cfg':22s} {'range':12s} | {'profit%':>10s} {'maxdd%':>8s} "
        f"{'sharpe':>7s} {'sortino':>8s} {'tr':>4s}"
    )
    print(hdr)
    print("-" * len(hdr))
    for sym, (biw, bow) in WINDOWS_BASELINE.items():
        if sym not in best or sym not in a.pairs.split(","):
            continue
        hiw, how = best[sym]
        for rng in (RANGE_FULL, RANGE_OOS):
            for label, strat, w, env in (
                (f"base {biw}/{bow}", "T2Momentum", (biw, bow), None),
                (f"best {hiw}/{how}", "T2MomentumHyper", (hiw, how), {"T2_IN_W": str(hiw), "T2_OUT_W": str(how)}),
            ):
                st = run_bt(sym, strat, w, rng, env)
                print(
                    f"{sym:5s} {label:22s} {rng:12s} | {st['profit']:10.1f} "
                    f"{st['maxdd']:8.1f} {st['sharpe']:7.2f} {st['sortino']:8.2f} "
                    f"{st['trades']:4d}"
                )
        print("-" * len(hdr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
