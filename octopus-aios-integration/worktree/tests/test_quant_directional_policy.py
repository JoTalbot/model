"""Pure tests for fail-closed directional-v2 policy."""

from __future__ import annotations

import pytest

from swarm.quant.quant_directional_policy import (
    DirectionalV2Config,
    bearish_exit_confirmed,
    entry_block_reason,
    portfolio_equity,
)


def _allowed(**overrides):
    config = DirectionalV2Config(entry_mode="enabled", require_ml=True, **overrides)
    analysis = {
        "signal": "BUY_LONG",
        "confidence": 0.90,
        "ml_prob_up": 0.70,
        "rl_position": 0.60,
    }
    return config, analysis


def test_default_policy_freezes_entries(monkeypatch):
    monkeypatch.delenv("OCTOPUS_QUANT_ENTRY_MODE", raising=False)
    config = DirectionalV2Config.from_env()

    assert config.entry_mode == "freeze"
    assert config.max_global_positions == 2
    assert config.max_positions_per_exchange == 1
    assert config.round_trip_cost_pct(0.0015) == pytest.approx(0.5)


def test_entry_gate_requires_cost_aware_signal_confirmation():
    config, analysis = _allowed()
    kwargs = {
        "exchange": "kucoin",
        "global_positions": 0,
        "exchange_positions": 0,
        "drawdown_pct": 0.0,
        "daily_loss_pct": 0.0,
        "candle_is_new": True,
    }

    assert entry_block_reason(config, analysis, **kwargs) is None
    assert (
        entry_block_reason(config, {**analysis, "confidence": 0.7}, **kwargs)
        == "confidence_below_min"
    )
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.55}, **kwargs)
        == "ml_not_confirmed"
    )
    assert (
        entry_block_reason(config, {**analysis, "rl_position": 0.1}, **kwargs)
        == "rl_veto"
    )
    assert (
        entry_block_reason(config, analysis, **{**kwargs, "drawdown_pct": 0.5})
        == "global_drawdown_kill"
    )
    assert (
        entry_block_reason(config, analysis, **{**kwargs, "global_positions": 2})
        == "global_position_limit"
    )
    assert (
        entry_block_reason(config, analysis, **{**kwargs, "unpriced_positions": 1})
        == "unpriced_positions"
    )


def test_execution_prices_include_conservative_costs():
    config = DirectionalV2Config(half_spread_rate=0.001, slippage_rate=0.0005)

    assert config.entry_execution_price(100.0) == pytest.approx(100.15)
    assert config.exit_execution_price(100.0) == pytest.approx(99.85)


def test_portfolio_equity_marks_positions_and_counts_unpriced():
    data = {
        "kraken": {
            "initial_balance_usd": 1_000.0,
            "cash_usd": 800.0,
            "positions": {
                "BTCUSD": {"qty": 2.0, "entry_price": 100.0},
                "ETHUSD": {"qty": 1.0, "entry_price": 50.0},
            },
        }
    }

    initial, equity, unpriced = portfolio_equity(
        data, {"kraken": {"BTC": 110.0}}, ("kraken",)
    )

    assert initial == 1_000.0
    assert equity == pytest.approx(1_070.0)
    assert unpriced == 1


def test_bearish_signal_requires_hold_confidence_and_ml_confirmation():
    config = DirectionalV2Config(
        min_confidence=0.8, min_hold_seconds=3_600, bearish_ml_max=0.4
    )
    analysis = {"signal": "SELL_SHORT", "confidence": 0.9, "ml_prob_up": 0.3}

    assert bearish_exit_confirmed(config, analysis, held_seconds=3_601)
    assert not bearish_exit_confirmed(config, analysis, held_seconds=100)
    assert not bearish_exit_confirmed(
        config, {**analysis, "ml_prob_up": 0.5}, held_seconds=3_601
    )


def _entry_kwargs():
    return {
        "exchange": "kucoin",
        "global_positions": 0,
        "exchange_positions": 0,
        "drawdown_pct": 0.0,
        "daily_loss_pct": 0.0,
        "candle_is_new": True,
    }


def test_ml_gate_calibration_lowers_threshold_to_q90(tmp_path):
    cal_file = tmp_path / "ml_prob_calibration.json"
    cal_file.write_text('{"threshold_q90": 0.5061}', encoding="utf-8")
    config, analysis = _allowed(ml_calibrate=True, ml_calibrate_file=str(cal_file))
    # ml_min_prob_up=0.60 (default) + calibrated q90=0.5061 -> effective min(0.60, 0.5061)
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.51}, **_entry_kwargs())
        is None
    )
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.50}, **_entry_kwargs())
        == "ml_not_confirmed"
    )


def test_ml_gate_calibration_respects_floor_and_cap(tmp_path):
    cal_file = tmp_path / "ml_prob_calibration.json"
    cal_file.write_text('{"threshold_q90": 0.45}', encoding="utf-8")
    # floor 0.50 wins
    config, analysis = _allowed(ml_calibrate=True, ml_calibrate_file=str(cal_file))
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.51}, **_entry_kwargs())
        is None
    )
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.49}, **_entry_kwargs())
        == "ml_not_confirmed"
    )
    # cap: owner's ml_min_prob_up never exceeded by calibration
    cal_file.write_text('{"threshold_q90": 0.99}', encoding="utf-8")
    config = DirectionalV2Config(
        entry_mode="enabled",
        require_ml=True,
        ml_calibrate=True,
        ml_calibrate_file=str(cal_file),
    )
    # calibrated 0.99 is capped by ml_min_prob_up=0.60 -> 0.59 blocked, 0.61 allowed
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.59}, **_entry_kwargs())
        == "ml_not_confirmed"
    )
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.61}, **_entry_kwargs())
        is None
    )


def test_ml_gate_calibration_missing_file_falls_back_to_cap(tmp_path):
    config, analysis = _allowed(
        ml_calibrate=True, ml_calibrate_file=str(tmp_path / "nope.json")
    )
    # q90 file missing -> fall back to ml_min_prob_up=0.60 (strict, fail-closed)
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.59}, **_entry_kwargs())
        == "ml_not_confirmed"
    )
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.61}, **_entry_kwargs())
        is None
    )


def test_ml_gate_calibration_disabled_keeps_static_threshold(tmp_path):
    cal_file = tmp_path / "ml_prob_calibration.json"
    cal_file.write_text('{"threshold_q90": 0.45}', encoding="utf-8")
    config, analysis = _allowed(ml_calibrate=False, ml_calibrate_file=str(cal_file))
    # static ml_min_prob_up=0.60 stays authoritative
    assert (
        entry_block_reason(config, {**analysis, "ml_prob_up": 0.55}, **_entry_kwargs())
        == "ml_not_confirmed"
    )
