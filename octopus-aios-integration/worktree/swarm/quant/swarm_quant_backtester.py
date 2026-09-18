"""
AIOS Swarm Quant Backtester & Strategy Optimizer (v19.0.0)
Бэктестинг торговых стратегий (Take-Profit +2%, Stop-Loss -1%) и ройный консенсус ИИ-агентов.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from swarm.quant.llm_swarm_debate import LLMSwarm
from swarm.quant.paths import resolve_data_dir
from swarm.quant.quant_trading_engine import QuantSignalEngine

logger = logging.getLogger("Octopus.SwarmBacktester")


class SwarmQuantBacktester:
    """Интеллектуальный бэктестер торговых стратегий с привлечением ИИ-Роя."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = resolve_data_dir(data_dir)

        self.signal_engine = QuantSignalEngine(data_dir)
        self.swarm = LLMSwarm()

    def run_backtest_simulation(self) -> dict[str, Any]:
        """Симуляция стратегии на накопленных исторических данных."""
        history = self.signal_engine.load_history()

        sim_results = {}
        for sym, prices in history.items():
            if len(prices) < 5:
                continue

            # Симуляция сделок по правилам Take-Profit (+2%) и Stop-Loss (-1%)
            trades = []
            position = None
            cash = 1000.0

            for i in range(4, len(prices)):
                p = prices[i]
                sub_prices = prices[: i + 1]

                # Сигналы
                fast_sma = sum(sub_prices[-3:]) / 3.0
                slow_sma = sum(sub_prices[-5:]) / 5.0

                if position is None and fast_sma > slow_sma:
                    position = {
                        "entry": p,
                        "invested": cash * 0.2,
                        "qty": (cash * 0.2) / p,
                    }
                    cash -= position["invested"]
                elif position is not None:
                    pnl_pct = ((p - position["entry"]) / position["entry"]) * 100.0
                    should_close = False
                    reason = ""

                    if pnl_pct >= 2.0:
                        should_close = True
                        reason = "TAKE_PROFIT"
                    elif pnl_pct <= -1.0:
                        should_close = True
                        reason = "STOP_LOSS"
                    elif fast_sma < slow_sma:
                        should_close = True
                        reason = "SMA_CROSS_BEAR"

                    if should_close:
                        val = position["qty"] * p
                        pnl = val - position["invested"]
                        cash += val
                        trades.append(
                            {"pnl_pct": pnl_pct, "pnl_usd": pnl, "reason": reason}
                        )
                        position = None

            win_trades = [t for t in trades if t["pnl_usd"] > 0]
            win_rate = (len(win_trades) / len(trades) * 100.0) if trades else 0.0
            net_pnl = sum(t["pnl_usd"] for t in trades)

            sim_results[sym] = {
                "ticks_analyzed": len(prices),
                "total_trades": len(trades),
                "winning_trades": len(win_trades),
                "win_rate_pct": round(win_rate, 1),
                "net_pnl_usd": round(net_pnl, 2),
                "final_portfolio_cash": round(cash, 2),
            }

        # Запуск Swarm-дебатов по результатам симуляции
        debate_topic = f"Анализ результатов бэктестинга квант-стратегии AIOS (TP +2%, SL -1%): {json.dumps(sim_results, ensure_ascii=False)}"
        logger.info("🧠 [SwarmBacktester] Запуск ройного консенсуса...")
        swarm_decision = self.swarm.start_debate(debate_topic)

        return {
            "status": "success",
            "simulation_metrics": sim_results,
            "swarm_consensus": swarm_decision,
        }
