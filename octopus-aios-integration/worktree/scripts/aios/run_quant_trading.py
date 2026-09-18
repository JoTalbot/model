#!/usr/bin/env python3
"""AIOS paper-only quantitative trading service runner."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

OCTOPUS_ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
if str(OCTOPUS_ROOT) not in sys.path:
    sys.path.insert(0, str(OCTOPUS_ROOT))

from swarm.quant.quant_trading_engine import (  # noqa: E402
    MultiExchangeQuantEngine,
    QuantMasterOrchestrator,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Octopus.RunQuantTrading")


def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_engines():
    """Build isolated paper engines; legacy duplicate execution is opt-in."""

    legacy = (
        QuantMasterOrchestrator()
        if _env_enabled("OCTOPUS_QUANT_LEGACY_EXECUTION")
        else None
    )
    filename = os.environ.get(
        "OCTOPUS_QUANT_PORTFOLIO_FILE", "multi_exchange_portfolios_v2.json"
    )
    return legacy, MultiExchangeQuantEngine(portfolio_filename=filename)


def run_cycle(legacy, multi_engine) -> dict:
    """Run one cycle and return signals/trades/risk without real orders."""

    legacy_result = (
        legacy.run_quant_cycle()
        if legacy is not None
        else {"signals": [], "legacy_execution": False}
    )
    multi_result = multi_engine.run_multi_exchange_cycle()
    risk = multi_result.get("risk", {})
    logger.info(
        "🏛️ [DirectionalV2] trades=%s entry_mode=%s drawdown=%.3f%% daily=%.3f%% blocks=%s",
        len(multi_result.get("cycle_trades", [])),
        risk.get("entry_mode", "unknown"),
        float(risk.get("drawdown_pct", 0.0) or 0.0),
        float(risk.get("daily_loss_pct", 0.0) or 0.0),
        risk.get("block_reasons", {}),
    )
    for trade in multi_result.get("cycle_trades", []):
        logger.info(trade_line(trade))
    for signal in legacy_result.get("signals", []):
        if signal.get("signal") != "HOLD":
            logger.info(
                "🚨 [QUANT SIGNAL] %s: %s confidence=%.1f%%",
                signal.get("symbol"),
                signal.get("signal"),
                float(signal.get("confidence", 0.0)) * 100.0,
            )
    return {"legacy": legacy_result, "multi": multi_result}


def trade_line(trade: dict) -> str:
    """One-line introspection of a paper trade (unit-tested)."""

    loc = f"{trade.get('exchange', '?')}:{trade.get('symbol', '?')}"
    if trade.get("action") == "BUY_LONG":
        return (
            f"🔎 [TRADE] {loc} BUY_LONG mid={trade.get('mid_price'):.4f} "
            f"exec={trade.get('execution_price'):.4f} fees={trade.get('fees_usd', 0.0):.4f} "
            f"exec_cost={trade.get('execution_cost_usd', 0.0):.4f} "
            f"conf={trade.get('signal_confidence')} ml_up={trade.get('ml_prob_up')}"
        )
    return (
        f"🔎 [TRADE] {loc} CLOSE({trade.get('reason', '?')}) mid={trade.get('mid_price'):.4f} "
        f"net={trade.get('net_pnl_usd', 0.0):+.4f} gross={trade.get('gross_pnl_usd', 0.0):+.4f} "
        f"fees={trade.get('fees_usd', 0.0):.4f}"
    )


def run_daemon(interval_seconds: int = 900) -> None:
    logger.info(
        "📈 Directional v2 paper daemon: interval=%ss (real orders disabled)",
        interval_seconds,
    )
    legacy, multi_engine = build_engines()
    while True:
        try:
            run_cycle(legacy, multi_engine)
        except Exception:
            logger.exception("❌ Ошибка в цикле Directional v2")
        time.sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="AIOS cost-aware paper trading runner")
    parser.add_argument("--daemon", action="store_true", help="run continuously")
    parser.add_argument(
        "--interval", type=int, default=900, help="daemon interval in seconds"
    )
    args = parser.parse_args()

    if args.daemon:
        run_daemon(interval_seconds=args.interval)
        return 0
    legacy, multi_engine = build_engines()
    print(json.dumps(run_cycle(legacy, multi_engine), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
