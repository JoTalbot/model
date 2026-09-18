"""Tests: режимный движок и kill-guard политики."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarm.quant.market_regime import (
    classify_regime,
    next_regime_triggers,
    regime_payload,
    risk_level,
    strategy_family,
)
from swarm.quant.regime_guard import crash_kill_active, current_regime


def _i(**kw):
    base = {
        "btc_above_sma200": None,
        "btc_above_sma50": None,
        "btc_ret_7d_pct": None,
        "dd90_pct": None,
        "vol30_annualized_pct": None,
        "breadth_7d": None,
        "fear_greed": None,
        "eth_btc_7d": None,
    }
    base.update(kw)
    return base


def test_panic_on_deep_drawdown():
    assert classify_regime(_i(dd90_pct=-36)) == "PANIC"


def test_panic_on_extreme_fear():
    assert classify_regime(_i(fear_greed=10)) == "PANIC"


def test_crash_on_moderate_drawdown_or_crash_ret():
    assert classify_regime(_i(dd90_pct=-22)) == "CRASH"
    assert classify_regime(_i(btc_ret_7d_pct=-18)) == "CRASH"


def test_bear_below_sma200_with_drawdown_or_negative_ret():
    assert classify_regime(_i(btc_above_sma200=0, dd90_pct=-12)) == "BEAR"
    assert classify_regime(_i(btc_above_sma200=0, btc_ret_7d_pct=-3)) == "BEAR"


def test_sideways_below_sma200_but_recovering():
    assert (
        classify_regime(
            _i(btc_above_sma200=0, btc_above_sma50=1, btc_ret_7d_pct=2, dd90_pct=-9)
        )
        == "SIDEWAYS"
    )


def test_strong_bull_and_bull():
    assert (
        classify_regime(
            _i(btc_above_sma200=1, btc_above_sma50=1, breadth_7d=0.8, fear_greed=70)
        )
        == "STRONG_BULL"
    )
    assert (
        classify_regime(_i(btc_above_sma200=1, btc_above_sma50=1, breadth_7d=0.55))
        == "BULL"
    )


def test_volatile():
    assert (
        classify_regime(
            _i(
                btc_above_sma200=1,
                btc_above_sma50=1,
                breadth_7d=0.3,
                vol30_annualized_pct=95,
            )
        )
        == "VOLATILE"
    )


def test_sideways_default():
    assert (
        classify_regime(
            _i(
                btc_above_sma200=1,
                btc_above_sma50=1,
                breadth_7d=0.4,
                vol30_annualized_pct=30,
            )
        )
        == "SIDEWAYS"
    )


def test_risk_and_strategy_mapping():
    assert risk_level("PANIC") == "EXTREME"
    assert risk_level("BEAR") == "HIGH"
    assert strategy_family("CRASH") == "сохранение капитала (кэш)"
    assert "momentum" in strategy_family("STRONG_BULL")


def test_triggers_for_bear_mention_sma200_and_crash_thresholds():
    i = _i(
        btc_above_sma200=0,
        btc_above_sma50=1,
        dd90_pct=-16,
        breadth_7d=0.5,
        vol30_annualized_pct=22,
        fear_greed=46,
    )
    t = next_regime_triggers(i, "BEAR")
    joined = " ".join(t)
    assert "SMA200" in joined
    assert "-20%" in joined


def test_payload_shape():
    p = regime_payload(_i(btc_above_sma200=0, dd90_pct=-12))
    assert p["regime"] == "BEAR"
    assert p["risk_level"] == "HIGH"
    assert "indicators" in p and "triggers" in p


def test_guard_blocks_in_crash(tmp_path):
    f = tmp_path / "regime.json"
    f.write_text(json.dumps({"regime": "CRASH"}))
    assert current_regime(str(f)) == "CRASH"
    assert crash_kill_active(str(f)) is True


def test_guard_allows_in_bear_and_missing_file(tmp_path):
    f = tmp_path / "regime.json"
    f.write_text(json.dumps({"regime": "BEAR"}))
    assert crash_kill_active(str(f)) is False
    assert crash_kill_active(str(tmp_path / "nope.json")) is False
    assert current_regime(str(tmp_path / "nope.json")) is None
