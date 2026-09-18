"""Pure risk and execution-cost policy for directional paper trading v2."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swarm.quant.ml_gate_calibration import calibrated_ml_threshold
from swarm.quant.regime_guard import crash_kill_active


def _data_dir() -> Path:
    return Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DirectionalV2Config:
    """Fail-closed paper-entry policy; exits are managed separately."""

    entry_mode: str = "freeze"
    allowed_exchanges: frozenset[str] = frozenset()
    max_global_positions: int = 2
    max_positions_per_exchange: int = 1
    max_drawdown_pct: float = 0.5
    max_daily_loss_pct: float = 0.5
    min_confidence: float = 0.82
    require_ml: bool = True
    ml_min_prob_up: float = 0.60
    rl_veto_position: float = 0.30
    bearish_ml_max: float = 0.40
    min_hold_seconds: int = 7_200
    half_spread_rate: float = 0.0005
    slippage_rate: float = 0.0005
    candle_seconds: int = 3_600
    take_profit_pct: float = 0.02
    stop_loss_pct: float = -0.01
    trail_ratio: float = 0.988
    ml_calibrate: bool = False
    ml_calibrate_file: str = "data/quant/ml_prob_calibration.json"
    ml_calibrate_floor: float = 0.50
    regime_guard: bool = False
    regime_file: str = "data/reports/market_regime_latest.json"

    @classmethod
    def from_env(cls) -> DirectionalV2Config:
        allowed = frozenset(
            item.strip().lower()
            for item in os.environ.get("OCTOPUS_QUANT_ALLOWED_EXCHANGES", "").split(",")
            if item.strip()
        )
        return cls(
            entry_mode=os.environ.get("OCTOPUS_QUANT_ENTRY_MODE", "freeze")
            .strip()
            .lower(),
            allowed_exchanges=allowed,
            max_global_positions=max(
                0, int(os.environ.get("OCTOPUS_QUANT_MAX_GLOBAL_POSITIONS", "2"))
            ),
            max_positions_per_exchange=max(
                0, int(os.environ.get("OCTOPUS_QUANT_MAX_PER_EXCHANGE", "1"))
            ),
            max_drawdown_pct=max(
                0.0, float(os.environ.get("OCTOPUS_QUANT_MAX_DRAWDOWN_PCT", "0.5"))
            ),
            max_daily_loss_pct=max(
                0.0, float(os.environ.get("OCTOPUS_QUANT_MAX_DAILY_LOSS_PCT", "0.5"))
            ),
            min_confidence=min(
                1.0,
                max(0.0, float(os.environ.get("OCTOPUS_QUANT_MIN_CONFIDENCE", "0.82"))),
            ),
            require_ml=_env_bool("OCTOPUS_QUANT_REQUIRE_ML", True),
            ml_min_prob_up=min(
                1.0,
                max(0.0, float(os.environ.get("OCTOPUS_QUANT_ML_MIN_PROB", "0.60"))),
            ),
            rl_veto_position=min(
                1.0, max(0.0, float(os.environ.get("OCTOPUS_QUANT_RL_VETO", "0.30")))
            ),
            bearish_ml_max=min(
                1.0,
                max(0.0, float(os.environ.get("OCTOPUS_QUANT_BEARISH_ML_MAX", "0.40"))),
            ),
            min_hold_seconds=max(
                0, int(os.environ.get("OCTOPUS_QUANT_MIN_HOLD_SECONDS", "7200"))
            ),
            half_spread_rate=max(
                0.0, float(os.environ.get("OCTOPUS_QUANT_HALF_SPREAD_RATE", "0.0005"))
            ),
            slippage_rate=max(
                0.0, float(os.environ.get("OCTOPUS_QUANT_SLIPPAGE_RATE", "0.0005"))
            ),
            candle_seconds=max(
                60, int(os.environ.get("OCTOPUS_QUANT_CANDLE_SECONDS", "3600"))
            ),
            take_profit_pct=max(
                0.0, float(os.environ.get("OCTOPUS_QUANT_TAKE_PROFIT_PCT", "0.02"))
            ),
            stop_loss_pct=min(
                0.0, float(os.environ.get("OCTOPUS_QUANT_STOP_LOSS_PCT", "-0.01"))
            ),
            trail_ratio=min(
                1.0,
                max(0.0, float(os.environ.get("OCTOPUS_QUANT_TRAIL_RATIO", "0.988"))),
            ),
            ml_calibrate=_env_bool("OCTOPUS_QUANT_ML_CALIBRATE", False),
            ml_calibrate_file=os.environ.get(
                "OCTOPUS_QUANT_ML_CALIBRATE_FILE",
                str(_data_dir() / "quant" / "ml_prob_calibration.json"),
            ),
            ml_calibrate_floor=min(
                1.0,
                max(
                    0.0,
                    float(os.environ.get("OCTOPUS_QUANT_ML_CALIBRATE_FLOOR", "0.50")),
                ),
            ),
            regime_guard=_env_bool("OCTOPUS_QUANT_REGIME_GUARD", False),
            regime_file=os.environ.get(
                "OCTOPUS_QUANT_REGIME_FILE",
                str(_data_dir() / "reports" / "market_regime_latest.json"),
            ),
        )

    def entry_execution_price(self, mid_price: float) -> float:
        return mid_price * (1.0 + self.half_spread_rate + self.slippage_rate)

    def exit_execution_price(self, mid_price: float) -> float:
        return mid_price * max(0.0, 1.0 - self.half_spread_rate - self.slippage_rate)

    def round_trip_cost_pct(self, fee_rate: float) -> float:
        return 200.0 * (fee_rate + self.half_spread_rate + self.slippage_rate)


def count_open_positions(data: dict[str, Any], exchanges: tuple[str, ...]) -> int:
    return sum(
        len((data.get(exchange) or {}).get("positions") or {}) for exchange in exchanges
    )


def portfolio_equity(
    data: dict[str, Any],
    prices: dict[str, dict[str, float]],
    exchanges: tuple[str, ...],
) -> tuple[float, float, int]:
    """Return initial, marked equity and unpriced count without mutating state."""

    total_initial = total_equity = 0.0
    unpriced = 0
    for exchange in exchanges:
        portfolio = data.get(exchange) or {}
        total_initial += float(portfolio.get("initial_balance_usd", 0.0) or 0.0)
        equity = float(portfolio.get("cash_usd", 0.0) or 0.0)
        exchange_prices = prices.get(exchange) or {}
        for key, position in (portfolio.get("positions") or {}).items():
            symbol = key.removesuffix("USD")
            price = float(exchange_prices.get(symbol, 0.0) or 0.0)
            if price <= 0.0:
                price = float(
                    position.get("entry_mid_price", position.get("entry_price", 0.0))
                    or 0.0
                )
                unpriced += 1
            equity += float(position.get("qty", 0.0) or 0.0) * price
        total_equity += equity
    return total_initial, total_equity, unpriced


def entry_block_reason(
    config: DirectionalV2Config,
    analysis: dict[str, Any],
    *,
    exchange: str,
    global_positions: int,
    exchange_positions: int,
    drawdown_pct: float,
    daily_loss_pct: float,
    unpriced_positions: int = 0,
    candle_is_new: bool,
) -> str | None:
    """Return a stable reason code; None means a paper entry is allowed."""

    if config.entry_mode != "enabled":
        return "entry_mode_freeze"
    if config.regime_guard and crash_kill_active(config.regime_file):
        return "regime_crash_kill"
    if not candle_is_new:
        return "same_candle"
    if config.allowed_exchanges and exchange.lower() not in config.allowed_exchanges:
        return "exchange_not_allowed"
    if global_positions >= config.max_global_positions:
        return "global_position_limit"
    if exchange_positions >= config.max_positions_per_exchange:
        return "exchange_position_limit"
    if drawdown_pct >= config.max_drawdown_pct:
        return "global_drawdown_kill"
    if daily_loss_pct >= config.max_daily_loss_pct:
        return "daily_loss_kill"
    if unpriced_positions > 0:
        return "unpriced_positions"
    if float(analysis.get("confidence", 0.0) or 0.0) < config.min_confidence:
        return "confidence_below_min"
    ml_prob = analysis.get("ml_prob_up")
    if config.require_ml:
        ml_min = config.ml_min_prob_up
        if config.ml_calibrate:
            calibrated = calibrated_ml_threshold(config.ml_calibrate_file)
            if calibrated is not None:
                ml_min = min(ml_min, max(config.ml_calibrate_floor, calibrated))
        if ml_prob is None or float(ml_prob) < ml_min:
            return "ml_not_confirmed"
    rl_position = analysis.get("rl_position")
    if rl_position is not None and float(rl_position) <= config.rl_veto_position:
        return "rl_veto"
    return None


def bearish_exit_confirmed(
    config: DirectionalV2Config, analysis: dict[str, Any], *, held_seconds: float
) -> bool:
    if analysis.get("signal") != "SELL_SHORT" or held_seconds < config.min_hold_seconds:
        return False
    if float(analysis.get("confidence", 0.0) or 0.0) < config.min_confidence:
        return False
    ml_prob = analysis.get("ml_prob_up")
    return ml_prob is not None and float(ml_prob) <= config.bearish_ml_max
