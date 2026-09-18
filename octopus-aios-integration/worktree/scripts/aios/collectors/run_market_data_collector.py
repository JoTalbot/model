#!/usr/bin/env python3
"""
Octopus Quant ML Engine - Демон сбора рыночных данных (Этап 2.1)

Запуск на VPS:
    python scripts/aios/collectors/run_market_data_collector.py daemon --interval 900 --timeframe 1h --limit 500 --orderbooks
    python scripts/aios/collectors/run_market_data_collector.py once --symbols BTC ETH SOL --timeframe 1h --limit 300
"""

from __future__ import annotations

import argparse
import logging
import time

from swarm.quant.data_collector import DEFAULT_SYMBOLS, MarketDataCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AIOS.MarketDataCollector")


def run_cycle(symbols, exchanges, timeframe, limit, with_orderbooks: bool) -> None:
    # Uniswap V3 обрабатывается отдельно через The Graph
    uniswap_enabled = exchanges and "uniswap_v3" in exchanges
    cex_exchanges = [e for e in (exchanges or []) if e != "uniswap_v3"] or None

    c = MarketDataCollector(symbols=symbols, exchanges=cex_exchanges)
    summary = c.collect_ohlcv_all(timeframe=timeframe, limit=limit)
    total = sum(sum(cnt.values()) for cnt in summary.values())
    logger.info("Собрано свечей (CEX): %d по %d активам", total, len(summary))

    if uniswap_enabled:
        try:
            from swarm.quant.defi.uniswap_v3 import UniswapV3Collector  # Wave 5e

            u3 = UniswapV3Collector()
            usum = u3.collect_all(since_hours_ago=720)
            logger.info("Uniswap V3 пулов собрано: %s", usum)
        except Exception as e:
            logger.error("Uniswap V3: %s", e)

    if with_orderbooks:
        for base in symbols:
            try:
                ob = c.collect_orderbooks(base)
                logger.info("Стакан %s: %s", base, {k: v.get("best_bid") for k, v in ob.items()})
            except Exception as e:
                logger.error("Стакан %s: %s", base, e)
    # периодический экспорт для Colab
    try:
        path = c.export_for_colab()
        logger.info("Экспорт для Colab: %s", path)
    except Exception as e:
        logger.error("Экспорт: %s", e)


def run_daemon(interval, symbols, exchanges, timeframe, limit, with_orderbooks) -> None:
    logger.info("🚀 [MarketDataCollector] Демон запущен (интервал %ss, tf=%s)...", interval, timeframe)
    while True:
        try:
            run_cycle(symbols, exchanges, timeframe, limit, with_orderbooks)
        except Exception as e:
            logger.error("Ошибка цикла: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="AIOS Quant Market Data Collector Daemon")
    ap.add_argument("mode", choices=["once", "daemon"])
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--exchanges", nargs="*", default=None)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--orderbooks", action="store_true")
    ap.add_argument("--interval", type=int, default=900)
    args = ap.parse_args()

    symbols = args.symbols or DEFAULT_SYMBOLS
    if args.mode == "daemon":
        run_daemon(args.interval, symbols, args.exchanges, args.timeframe, args.limit, args.orderbooks)
    else:
        run_cycle(symbols, args.exchanges, args.timeframe, args.limit, args.orderbooks)
