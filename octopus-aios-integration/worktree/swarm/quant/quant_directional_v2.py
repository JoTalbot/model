"""Cost-aware paper execution cycle for the multi-exchange quant engine.

Kept separate from market adapters/reporting so risk policy can evolve without
regrowing ``swarm.quant.quant_trading_engine``.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from swarm.quant.quant_directional_policy import (
    DirectionalV2Config,
    bearish_exit_confirmed,
    count_open_positions,
    entry_block_reason,
    portfolio_equity,
)


def _ensure_accounting(portfolio: dict[str, Any]) -> None:
    """Add v2 counters without rewriting historical net PnL."""

    entries = int(portfolio.get("entry_count", portfolio.get("total_trades", 0)) or 0)
    portfolio["accounting_version"] = 2
    portfolio["entry_count"] = entries
    portfolio["total_trades"] = entries  # backward-compatible alias
    portfolio.setdefault(
        "closed_trades", max(0, entries - len(portfolio.get("positions") or {}))
    )
    portfolio.setdefault("gross_pnl_usd", 0.0)
    portfolio.setdefault("fees_paid_usd", 0.0)
    portfolio.setdefault("execution_costs_usd", 0.0)
    portfolio.setdefault("net_profit_usd", 0.0)
    portfolio.setdefault("net_loss_usd", 0.0)
    portfolio.setdefault("winning_trades", 0)


def run_multi_exchange_cycle(engine) -> dict[str, Any]:
    """Run one paper-only, hourly-aligned, fail-closed directional-v2 cycle."""

    all_prices = engine.fetch_all_exchange_prices()
    data = engine.load_portfolios()
    config = DirectionalV2Config.from_env()
    now = time.time()
    cycle_trades: list[dict[str, Any]] = []
    block_reasons: Counter[str] = Counter()

    for exchange in engine.EXCHANGES:
        _ensure_accounting(data[exchange])

    initial, equity, unpriced = portfolio_equity(
        data, all_prices, tuple(engine.EXCHANGES)
    )
    drawdown_pct = max(
        0.0, ((initial - equity) / initial * 100.0) if initial > 0 else 0.0
    )
    risk_state = data.setdefault("_risk_state", {})
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if risk_state.get("day") != day:
        risk_state["day"] = day
        risk_state["day_start_equity_usd"] = equity
    day_start = float(risk_state.get("day_start_equity_usd", equity) or equity)
    daily_loss_pct = max(
        0.0, ((day_start - equity) / day_start * 100.0) if day_start > 0 else 0.0
    )
    candle_id = int(now // config.candle_seconds) - 1
    candle_is_new = int(risk_state.get("last_directional_candle", -1)) != candle_id
    global_positions = count_open_positions(data, tuple(engine.EXCHANGES))

    if candle_is_new:
        # Seed history once per closed candle, not four times per 1h candle.
        new_exchanges = {"coinbase", "kucoin", "bitfinex", "bitstamp", "mexc"}
        try:
            history = engine.signal_engine.load_history()
            for exchange in new_exchanges:
                for symbol, current in all_prices.get(exchange, {}).items():
                    key = f"{exchange.upper()}_{symbol}"
                    if key not in history or len(history.get(key, [])) < 20:
                        binance_key = f"BINANCE_{symbol}"
                        seed = list(history.get(binance_key, []))[-30:]
                        if current > 0:
                            seed = [*seed[-29:], current]
                        history[key] = seed
            engine.signal_engine.save_history(history)
        except Exception:
            block_reasons["history_seed_error"] += 1

        for exchange in engine.EXCHANGES:
            portfolio = data[exchange]
            prices = all_prices.get(exchange, {})
            positions = portfolio.get("positions", {})

            for symbol, mid_price in prices.items():
                if mid_price <= 0:
                    continue
                position_key = f"{symbol}USD"
                position = positions.get(position_key)
                if not position:
                    static_reason = entry_block_reason(
                        config,
                        {"confidence": 1.0, "ml_prob_up": 1.0, "rl_position": 1.0},
                        exchange=exchange,
                        global_positions=global_positions,
                        exchange_positions=len(positions),
                        drawdown_pct=drawdown_pct,
                        daily_loss_pct=daily_loss_pct,
                        unpriced_positions=unpriced,
                        candle_is_new=True,
                    )
                    if static_reason:
                        block_reasons[static_reason] += 1
                        continue

                analysis = engine.signal_engine.record_and_analyze(
                    f"{exchange.upper()}_{symbol}", mid_price
                )
                signal = analysis.get("signal", "HOLD")

                if signal == "BUY_LONG" and not position:
                    reason = entry_block_reason(
                        config,
                        analysis,
                        exchange=exchange,
                        global_positions=global_positions,
                        exchange_positions=len(positions),
                        drawdown_pct=drawdown_pct,
                        daily_loss_pct=daily_loss_pct,
                        unpriced_positions=unpriced,
                        candle_is_new=True,
                    )
                    reserve = (
                        float(
                            portfolio.get(
                                "initial_balance_usd", engine.INITIAL_PER_EXCHANGE
                            )
                        )
                        * engine.MIN_CASH_RESERVE_PCT
                    )
                    if not reason and float(portfolio.get("cash_usd", 0.0)) <= reserve:
                        reason = "cash_reserve"
                    if reason:
                        block_reasons[reason] += 1
                        continue

                    investment = min(float(portfolio["cash_usd"]) * 0.20, 200.0)
                    if investment < 10.0:
                        block_reasons["minimum_order"] += 1
                        continue
                    entry_fee = investment * engine.FEE_RATE
                    execution_price = config.entry_execution_price(mid_price)
                    quantity = (investment - entry_fee) / execution_price
                    execution_cost = quantity * (execution_price - mid_price)
                    portfolio["cash_usd"] -= investment
                    positions[position_key] = {
                        "side": "LONG",
                        "entry_price": execution_price,
                        "entry_mid_price": mid_price,
                        "qty": quantity,
                        "invested_usd": investment,
                        "entry_fee_usd": round(entry_fee, 8),
                        "entry_execution_cost_usd": round(execution_cost, 8),
                        "max_price_seen": mid_price,
                        "opened_at": now,
                        "signal_confidence": analysis.get("confidence"),
                        "ml_prob_up": analysis.get("ml_prob_up"),
                        "rl_position": analysis.get("rl_position"),
                    }
                    portfolio["positions"] = positions
                    portfolio["entry_count"] += 1
                    portfolio["total_trades"] = portfolio["entry_count"]
                    portfolio["fees_paid_usd"] += entry_fee
                    portfolio["execution_costs_usd"] += execution_cost
                    global_positions += 1
                    cycle_trades.append(
                        {
                            "exchange": exchange,
                            "action": "BUY_LONG",
                            "symbol": symbol,
                            "mid_price": mid_price,
                            "execution_price": execution_price,
                            "fees_usd": entry_fee,
                            "execution_cost_usd": execution_cost,
                            "ml_prob_up": analysis.get("ml_prob_up"),
                            "signal_confidence": analysis.get("confidence"),
                        }
                    )

                elif position:
                    quantity = float(position.get("qty", 0.0))
                    invested = float(position.get("invested_usd", 0.0))
                    exit_price = config.exit_execution_price(mid_price)
                    gross_proceeds = quantity * mid_price
                    execution_proceeds = quantity * exit_price
                    exit_fee = execution_proceeds * engine.FEE_RATE
                    net_proceeds = execution_proceeds - exit_fee
                    net_pnl = net_proceeds - invested
                    net_pnl_pct = (net_pnl / invested * 100.0) if invested > 0 else 0.0
                    entry_mid = float(
                        position.get(
                            "entry_mid_price", position.get("entry_price", mid_price)
                        )
                    )
                    gross_pnl = quantity * (mid_price - entry_mid)
                    exit_execution_cost = gross_proceeds - execution_proceeds
                    max_seen = max(
                        float(position.get("max_price_seen", entry_mid)), mid_price
                    )
                    position["max_price_seen"] = max_seen
                    held_seconds = max(0.0, now - float(position.get("opened_at", now)))

                    reason = ""
                    if net_pnl_pct >= config.take_profit_pct * 100.0:
                        reason = "take_profit"
                    elif net_pnl_pct <= config.stop_loss_pct * 100.0:
                        reason = "stop_loss"
                    elif (
                        max_seen > entry_mid * 1.01
                        and mid_price <= max_seen * config.trail_ratio
                    ):
                        reason = "trailing_stop"
                    elif bearish_exit_confirmed(
                        config, analysis, held_seconds=held_seconds
                    ):
                        reason = "confirmed_bearish_exit"

                    if reason:
                        portfolio["cash_usd"] += net_proceeds
                        portfolio["realized_pnl_usd"] += net_pnl
                        portfolio["gross_pnl_usd"] += gross_pnl
                        portfolio["fees_paid_usd"] += exit_fee
                        portfolio["execution_costs_usd"] += exit_execution_cost
                        portfolio["closed_trades"] += 1
                        if net_pnl > 0:
                            portfolio["winning_trades"] += 1
                            portfolio["net_profit_usd"] += net_pnl
                        else:
                            portfolio["net_loss_usd"] += abs(net_pnl)
                        del positions[position_key]
                        portfolio["positions"] = positions
                        global_positions -= 1
                        cycle_trades.append(
                            {
                                "exchange": exchange,
                                "action": "CLOSE",
                                "symbol": symbol,
                                "reason": reason,
                                "mid_price": mid_price,
                                "execution_price": exit_price,
                                "gross_pnl_usd": gross_pnl,
                                "fees_usd": float(position.get("entry_fee_usd", 0.0))
                                + exit_fee,
                                "execution_cost_usd": float(
                                    position.get("entry_execution_cost_usd", 0.0)
                                )
                                + exit_execution_cost,
                                "net_pnl_usd": net_pnl,
                            }
                        )
                        portfolio.setdefault("trade_log", []).append(
                            {
                                "ts": now,
                                "exchange": exchange,
                                "symbol": symbol,
                                "reason": reason,
                                "net_pnl_usd": net_pnl,
                            }
                        )

        risk_state["last_directional_candle"] = candle_id
    else:
        block_reasons["same_candle"] += 1

    risk_state.setdefault("started_at", now)
    risk_state["max_drawdown_pct_seen"] = max(
        float(risk_state.get("max_drawdown_pct_seen", 0.0) or 0.0), drawdown_pct
    )
    risk_state.update(
        {
            "policy": "cost_aware_directional_v2",
            "entry_mode": config.entry_mode,
            "equity_usd": round(equity, 8),
            "drawdown_pct": round(drawdown_pct, 6),
            "daily_loss_pct": round(daily_loss_pct, 6),
            "unpriced_positions": unpriced,
            "round_trip_cost_pct": round(
                config.round_trip_cost_pct(engine.FEE_RATE), 6
            ),
            "block_reasons": dict(block_reasons),
            "updated_at": now,
        }
    )

    # 2. Cross-exchange scan. Это только наблюдение котировок: ордера не
    # выставляются, капитал не резервируется, поэтому найденный spread/PnL
    # нельзя учитывать как заработанную прибыль портфеля.
    cross_arb = data.get("cross_arbitrage", {})
    legacy_pnl = float(
        cross_arb.get(
            "legacy_simulated_pnl_usd",
            cross_arb.get("arbitrage_pnl_usd", 0.0),
        )
        or 0.0
    )
    legacy_trades = int(
        cross_arb.get(
            "legacy_simulated_trades",
            cross_arb.get("total_arbitrage_trades", 0),
        )
        or 0
    )
    cross_arb.update(
        {
            "accounting_version": 2,
            "legacy_simulated_pnl_usd": legacy_pnl,
            "legacy_simulated_trades": legacy_trades,
            "settled_pnl_usd": float(cross_arb.get("settled_pnl_usd", 0.0) or 0.0),
            "settled_trades": int(cross_arb.get("settled_trades", 0) or 0),
            # Legacy keys now mean settled values for backward compatibility.
            "arbitrage_pnl_usd": float(cross_arb.get("settled_pnl_usd", 0.0) or 0.0),
            "total_arbitrage_trades": int(cross_arb.get("settled_trades", 0) or 0),
            "history": list(cross_arb.get("history", [])),
        }
    )
    scan_opportunities = 0
    scan_theoretical_pnl = 0.0
    quote_currency = {
        "kraken": "USD",
        "coinbase": "USD",
        "bitfinex": "USD",
        "bitstamp": "USD",
        "binance": "USDT",
        "bybit": "USDT",
        "okx": "USDT",
        "kucoin": "USDT",
        "mexc": "USDT",
    }
    symbols = [
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "ADA",
        "DOGE",
        "AVAX",
        "DOT",
        "LINK",
        "POL",
        "NEAR",
        "LTC",
        "UNI",
        "SHIB",
        "SUI",
        "APT",
        "ARB",
        "OP",
        "PEPE",
        "FET",
        "INJ",
        "ATOM",
        "XLM",
    ]

    for sym in symbols:
        sym_prices = {}
        for ex in engine.EXCHANGES:
            p = all_prices.get(ex, {}).get(sym, 0.0)
            if p > 0:
                sym_prices[ex] = p

        # Never compare USD with USDT as if they were the same asset.
        for quote in ("USD", "USDT"):
            comparable = {
                ex: price
                for ex, price in sym_prices.items()
                if quote_currency.get(ex) == quote
            }
            if len(comparable) < 2:
                continue
            min_ex = min(comparable, key=comparable.get)
            max_ex = max(comparable, key=comparable.get)
            p_low = comparable[min_ex]
            p_high = comparable[max_ex]
            spread_pct = ((p_high - p_low) / p_low) * 100.0

            if spread_pct >= (
                engine.MIN_NET_ARBITRAGE_SPREAD_PCT + 2 * engine.FEE_RATE * 100
            ):
                arb_trade_usd = 100.0
                net_spread_pct = spread_pct - (2 * engine.FEE_RATE * 100) - 0.20
                arb_pnl = (arb_trade_usd * net_spread_pct) / 100.0

                scan_opportunities += 1
                scan_theoretical_pnl += arb_pnl
                hist = cross_arb.get("history", [])
                hist.append(
                    {
                        "timestamp": time.time(),
                        "kind": "theoretical_opportunity",
                        "executed": False,
                        "quote_currency": quote,
                        "symbol": sym,
                        "buy_ex": min_ex,
                        "buy_price": p_low,
                        "sell_ex": max_ex,
                        "sell_price": p_high,
                        "spread_pct": round(spread_pct, 3),
                        "theoretical_pnl_usd": round(arb_pnl, 2),
                    }
                )
                cross_arb["history"] = hist[-30:]

    cross_arb["last_scan_at"] = time.time()
    cross_arb["last_scan_opportunities"] = scan_opportunities
    cross_arb["last_scan_theoretical_pnl_usd"] = round(scan_theoretical_pnl, 8)
    data["cross_arbitrage"] = cross_arb
    engine.save_portfolios(data)
    return {
        "cycle_trades": cycle_trades,
        "portfolios": data,
        "prices": all_prices,
        "risk": risk_state,
    }
