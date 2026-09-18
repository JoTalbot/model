# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires freqtrade backtest data + venv
#!/usr/bin/env python3
"""Tests for the freqtrade T2 port (freqtrade_t2.py).

Validates that the port reproduces the production T2 state machine
(run_t2_momentum.py):
- pair-aware windows (BNB/NEAR 50/50, others 50/40)
- level-based entry (close > sma_in) - not crossing
- exit via custom_exit on closed bars only (no lookahead)
- no exit on the entry candle
- end-to-end: freqtrade backtest == open-fill reference on identical data

Usage: pytest test_freqtrade_t2.py
"""

import json
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# overridable via env (server layout differs from local sandbox)
DATA = Path(os.environ.get("AIOS_FREQTRADE_DATA", str(HERE / "user_data" / "data" / "okx")))
RESULTS = Path(os.environ.get("AIOS_FREQTRADE_RESULTS", str(HERE / "user_data" / "backtest_results")))
STRATEGY_PATH = Path(os.environ.get("AIOS_FREQTRADE_STRATEGIES", str(HERE / "strategies")))
sys.path.insert(0, str(STRATEGY_PATH))  # canonical strategy module wins over any stale copy
CONFIGS = Path(os.environ.get("AIOS_FREQTRADE_CONFIGS", str(HERE / "configs")))
USERDIR = Path(os.environ.get("AIOS_FREQTRADE_USERDIR", str(HERE / "user_data")))
EXCHANGE = os.environ.get("AIOS_FREQTRADE_EXCHANGE", "okx")
TIMERANGE = os.environ.get("AIOS_FREQTRADE_TIMERANGE", "20190720-20260816")
FREQTRADE_BIN = os.environ.get("FREQTRADE_BIN", "freqtrade")

os.environ.setdefault("AIOS_FREQTRADE_DATA", str(DATA))
from reference_t2 import sim_open_fill  # noqa: E402

# ---------------------------------------------------------------- unit tests

_CFG = {"timeframe": "1d", "exchange": {"name": "okx"}, "stake_currency": "USDT", "candle_type_def": "spot"}


def _mk():
    from freqtrade_t2 import T2Momentum

    return T2Momentum(_CFG)


def test_pair_windows():
    from freqtrade_t2 import PER_PAIR_WINDOWS

    s = _mk()
    assert s._windows("BTC/USDT") == (50, 40)
    assert s._windows("ETH/USDT") == (50, 40)
    assert s._windows("SOL/USDT") == (50, 40)
    assert PER_PAIR_WINDOWS["BNB/USDT"] == (50, 50)
    assert PER_PAIR_WINDOWS["NEAR/USDT"] == (50, 50)


def test_indicators_and_signals():
    """populate_* produce level-based signals identical to production."""
    import pandas as pd

    s = _mk()
    closes = [float(i % 7) + 1.0 for i in range(300)]
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=300, freq="1D"),
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1.0] * 300,
        }
    )
    out = s.populate_indicators(df.copy(), {"pair": "BTC/USDT"})
    assert "sma_in" in out and "sma_out" in out
    # sma matches manual computation
    assert abs(out["sma_in"].iloc[249] - sum(closes[200:250]) / 50) < 1e-9
    # entry is LEVEL (close > sma_in), not crossing
    entry = s.populate_entry_trend(out.copy(), {"pair": "BTC/USDT"})
    for i in range(250, 290):
        exp = 1 if closes[i] > sum(closes[i - 49 : i + 1]) / 50 else 0
        val = entry["enter_long"].iloc[i]
        assert (0 if val != val else int(val)) == exp, f"row {i}"


def test_custom_exit_uses_closed_bars():
    """custom_exit must not look ahead: only bars with date < current_time."""
    import pandas as pd

    s = _mk()
    closes = [100.0 + i * 0.1 for i in range(300)]  # steady uptrend
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=300, freq="1D", tz="UTC"),
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1.0] * 300,
        }
    )
    df = s.populate_indicators(df, {"pair": "BTC/USDT"})

    class FakeTrade:
        open_date_utc = df["date"].iloc[200]  # trade opened at bar 200

    class FakeDP:
        def get_analyzed_dataframe(self, pair, tf):
            # simulate backtest state: dataframe available up to bar 250
            return df.iloc[:251].copy(), None

    s.dp = FakeDP()
    t = FakeTrade()
    # current_time = bar 251 open; last closed bar = 250 (close 125.0, sma ~124.8)
    cur = df["date"].iloc[251]
    assert s.custom_exit("BTC/USDT", t, cur, 125.0, 0.0) is None
    # no exit on the entry candle
    cur_entry = df["date"].iloc[200]
    assert s.custom_exit("BTC/USDT", t, cur_entry, 120.0, 0.0) is None
    # downtrend -> exit fires
    closes2 = [100.0 - i * 0.5 for i in range(300)]
    df2 = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=300, freq="1D", tz="UTC"),
            "open": closes2,
            "high": [c + 0.5 for c in closes2],
            "low": [c - 0.5 for c in closes2],
            "close": closes2,
            "volume": [1.0] * 300,
        }
    )
    df2 = s.populate_indicators(df2, {"pair": "BTC/USDT"})

    class FakeDP2:
        def get_analyzed_dataframe(self, pair, tf):
            return df2.iloc[:251].copy(), None

    s.dp = FakeDP2()
    assert s.custom_exit("BTC/USDT", t, cur, 25.0, 0.0) == "t2_sma_out"


# ----------------------------------------------------- end-to-end (slow, ~10s)


def _run_freqtrade_btc():
    import subprocess

    cfg = CONFIGS / "config_t2_BTC.json"
    if not cfg.exists():
        import argparse

        import run_validation

        run_validation.ARGS = argparse.Namespace(
            exchange=EXCHANGE,
            data_dir=DATA,
            configs_dir=CONFIGS,
            results_dir=RESULTS,
            strategy_path=STRATEGY_PATH,
            pairs=["BTC"],
        )
        run_validation.make_config("BTC")
    cmd = [
        FREQTRADE_BIN,
        "backtesting",
        "--strategy",
        "T2Momentum",
        "--strategy-path",
        str(STRATEGY_PATH),
        "--config",
        str(cfg),
        "--datadir",
        str(DATA),
        "--timerange",
        TIMERANGE,
        "--fee",
        "0.0015",
        "--data-format-ohlcv",
        "json",
        "--userdir",
        str(USERDIR),
        "--export",
        "trades",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    zips = sorted(RESULTS.glob("*.zip"))
    with zipfile.ZipFile(zips[-1]) as zf:
        name = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n][0]  # noqa: RUF015
        data = json.loads(zf.read(name))
    st = data["strategy"]["T2Momentum"]
    return {"trades": st["total_trades"], "profit": st["profit_total"] * 100}


def test_backtest_matches_open_fill_reference():
    """freqtrade backtest must match the open-fill reference within 10%."""
    rows = json.loads((DATA / "BTC_USDT-1d.json").read_text())
    closes = [r[4] for r in rows]
    opens = [r[1] for r in rows]
    tot, tr = sim_open_fill(closes, opens, 50, 40, 200)
    fq = _run_freqtrade_btc()
    dev = abs(fq["profit"] - (tot - 1) * 100) / ((tot - 1) * 100)
    assert dev < 0.10, f"freqtrade {fq['profit']:.1f}% vs ref {(tot - 1) * 100:.1f}% (dev {dev:.1%})"
    assert abs(fq["trades"] - len(tr) // 2) <= 1, f"trades {fq['trades']} vs {len(tr) // 2}"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
