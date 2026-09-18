# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires freqtrade venv
#!/usr/bin/env python3
"""Run freqtrade backtests per pair with the T2 port and compare against
two references on identical data:

- close-fill reference (production run_daily model: transact at signal-day close)
- open-fill reference (freqtrade model: transact at next-day open)

The port is validated against the OPEN-FILL reference (same execution model);
the close-fill numbers are production's optimistic model.

Usage:
    python run_validation.py [--exchange okx|binance] [--data-dir DIR]
                             [--configs-dir DIR] [--results-dir DIR]
                             [--strategy-path DIR] [--pairs BTC,ETH,...]
"""

import argparse
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAIRS = ["BTC", "ETH", "SOL", "BNB", "NEAR"]
WINDOWS = {"BTC": (50, 40), "ETH": (50, 40), "SOL": (50, 40), "BNB": (50, 50), "NEAR": (50, 50)}
FEE = "0.0015"
RANGE_START = "2019-07-20"  # freqtrade timerange start (after startup candles)

ARGS: argparse.Namespace | None = None
FREQTRADE_BIN = Path(__import__("os").environ.get("FREQTRADE_BIN", "freqtrade"))


def make_config(sym: str) -> Path:
    cfg = {
        "max_open_trades": 1,
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "tradable_balance_ratio": 0.99,
        "fiat_display_currency": "USD",
        "dry_run": True,
        "timeframe": "1d",
        "cancel_open_orders_on_exit": False,
        "trading_mode": "spot",
        "margin_mode": "",
        "unfilledtimeout": {"entry": 10, "exit": 10},
        "entry_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exchange": {
            "name": ARGS.exchange,
            "ccxt_config": {"options": {"fetchMarkets": {"types": ["spot"]}}},
            "ccxt_async_config": {"options": {"fetchMarkets": {"types": ["spot"]}}},
            "pair_whitelist": [f"{sym}/USDT"],
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
        "telegram": {"enabled": False, "token": "dummy", "chat_id": "dummy"},
        "api_server": {
            "enabled": False,
            "listen_ip_address": "127.0.0.1",
            "listen_port": 8099,
            "username": "dummy",
            "password": "dummy",
            "jwt_secret_key": "dummydummydummydummydummydummy123",
        },
        "bot_name": f"t2_momentum_{sym.lower()}",
        "initial_state": "running",
        "internals": {"process_throttle_secs": 5},
    }
    p = ARGS.configs_dir / f"config_t2_{sym}.json"
    p.write_text(json.dumps(cfg, indent=2))
    return p


def load_rows(sym: str) -> list[list]:
    return json.loads((ARGS.data_dir / f"{sym}_USDT-1d.json").read_text())


def run_backtest(sym: str) -> None:
    rows = load_rows(sym)
    start_s = time.strftime("%Y%m%d", time.gmtime(rows[0][0] / 1000))
    start_s = max(start_s, "20190720")
    end_s = time.strftime("%Y%m%d", time.gmtime(rows[-1][0] / 1000))
    make_config(sym)
    cmd = [
        str(FREQTRADE_BIN),
        "backtesting",
        "--strategy",
        "T2Momentum",
        "--strategy-path",
        str(ARGS.strategy_path),
        "--config",
        str(ARGS.configs_dir / f"config_t2_{sym}.json"),
        "--datadir",
        str(ARGS.data_dir),
        "--userdir",
        str(ARGS.userdir),
        "--timerange",
        f"{start_s}-{end_s}",
        "--fee",
        FEE,
        "--data-format-ohlcv",
        "json",
        "--userdir",
        str(ARGS.userdir),
        "--export",
        "trades",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        print((r.stdout + r.stderr)[-4000:])
        raise RuntimeError(f"freqtrade failed for {sym} (rc={r.returncode})")


def parse_result() -> dict:
    """Read the newest backtest result zip."""
    zips = sorted(ARGS.results_dir.glob("*.zip"))
    if not zips:
        raise RuntimeError("no backtest result zips")
    with zipfile.ZipFile(zips[-1]) as zf:
        name = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n][0]  # noqa: RUF015
        data = json.loads(zf.read(name))
    st = data["strategy"]["T2Momentum"]
    return {
        "trades": st["total_trades"],
        "tot_profit_pct": st["profit_total"] * 100,
        "cagr": (st["cagr"] or 0) * 100,
        "maxdd": st["max_drawdown_account"] * 100,
    }


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser(description="Validate freqtrade T2 port vs references")
    ap.add_argument("--exchange", default="okx")
    ap.add_argument("--data-dir", default=str(HERE / "user_data" / "data" / "okx"))
    ap.add_argument("--configs-dir", default=str(HERE / "configs"))
    ap.add_argument("--results-dir", default=str(HERE / "user_data" / "backtest_results"))
    ap.add_argument("--userdir", default=str(HERE / "user_data"))
    ap.add_argument("--strategy-path", default=str(HERE / "strategies"))
    ap.add_argument("--pairs", default="BTC,ETH,SOL,BNB,NEAR")
    a = ap.parse_args()
    ARGS = argparse.Namespace(
        exchange=a.exchange,
        data_dir=Path(a.data_dir),
        configs_dir=Path(a.configs_dir),
        results_dir=Path(a.results_dir),
        strategy_path=Path(a.strategy_path),
        userdir=Path(a.userdir),
        pairs=a.pairs.split(","),
    )
    ARGS.configs_dir.mkdir(parents=True, exist_ok=True)
    ARGS.results_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(HERE))
    from reference_t2 import sim_open_fill, t2_equity

    print(
        f"{'SYM':5s} | {'REF close':>10s} | {'REF open':>10s} | {'FQ':>10s} | {'FQ tr':>6s} | {'open tr':>7s} | verdict"
    )
    ok_all = True
    for sym in ARGS.pairs:
        rows = load_rows(sym)
        closes = [r[4] for r in rows]
        opens = [r[1] for r in rows]
        in_w, out_w = WINDOWS[sym]
        # close-fill reference (production model)
        eq, _ref_tr = t2_equity(closes, in_w, out_w)
        ref_close = (eq[-1] - 1.0) * 100
        # open-fill reference (freqtrade model), same range start as freqtrade
        start = 0
        for i, r in enumerate(rows):
            if time.strftime("%Y-%m-%d", time.gmtime(r[0] / 1000)) >= RANGE_START:
                start = i
                break
        start = max(start, 200)  # freqtrade startup candles: no trades in the first 200 bars
        tot, open_tr = sim_open_fill(closes, opens, in_w, out_w, start)
        ref_open = (tot - 1.0) * 100
        # freqtrade
        run_backtest(sym)
        st = parse_result()
        # verdict: freqtrade vs open-fill reference (same execution model)
        denom = max(ref_open, 1.0)
        dev = abs(st["tot_profit_pct"] - ref_open) / denom
        verdict = "OK" if dev < 0.10 else "CHECK"
        if verdict != "OK":
            ok_all = False
        print(
            f"{sym:5s} | {ref_close:10.1f} | {ref_open:10.1f} | {st['tot_profit_pct']:10.1f} | "
            f"{st['trades']:6d} | {len(open_tr) // 2:7d} | {verdict} (dev {dev:.1%})"
        )
    print("ALL OK" if ok_all else "SOME CHECK - inspect")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
