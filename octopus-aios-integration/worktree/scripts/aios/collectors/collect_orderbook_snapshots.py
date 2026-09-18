#!/usr/bin/env python3
"""Collect public orderbook snapshots for research; never authenticates or trades."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

try:
    import ccxt

    _CCXT_ERROR = None
except ImportError as e:  # prod venv has no ccxt
    ccxt = None
    _CCXT_ERROR = e

EXCHANGE_NAMES = ("binance", "kucoin", "mexc", "okx", "bitstamp", "coinbase")

# Some exchanges only accept specific depth limits (kucoin: 20 or 100).
MIN_DEPTH = {"kucoin": 20}

# Exchanges that do not list all universe pairs (bitstamp: BTC/ETH only).
EXCHANGE_SYMBOLS = {"bitstamp": {"BTC", "ETH"}}


class OrderbookStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30.0)
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS snapshots (
            ts REAL NOT NULL, exchange TEXT NOT NULL, symbol TEXT NOT NULL,
            bid REAL NOT NULL, ask REAL NOT NULL, mid REAL NOT NULL, spread_bps REAL NOT NULL,
            bid_depth_usd REAL NOT NULL, ask_depth_usd REAL NOT NULL,
            bids_json TEXT NOT NULL, asks_json TEXT NOT NULL, latency_ms REAL NOT NULL
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_ts ON snapshots(symbol, ts)")

    def add(self, row: dict):
        self.db.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(
                row[key]
                for key in (
                    "ts",
                    "exchange",
                    "symbol",
                    "bid",
                    "ask",
                    "mid",
                    "spread_bps",
                    "bid_depth_usd",
                    "ask_depth_usd",
                    "bids_json",
                    "asks_json",
                    "latency_ms",
                )
            ),
        )

    def prune(self, retention_days: int):
        self.db.execute("DELETE FROM snapshots WHERE ts < ?", (time.time() - retention_days * 86400,))
        self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()


def normalize(exchange: str, symbol: str, book: dict, latency_ms: float, depth: int = 10) -> dict | None:
    bids = [[float(p), float(q)] for p, q, *_ in (book.get("bids") or [])[:depth] if p and q]
    asks = [[float(p), float(q)] for p, q, *_ in (book.get("asks") or [])[:depth] if p and q]
    if not bids or not asks or asks[0][0] < bids[0][0]:
        return None
    bid, ask = bids[0][0], asks[0][0]
    mid = (bid + ask) / 2
    return {
        "ts": float((book.get("timestamp") or time.time() * 1000) / 1000),
        "exchange": exchange,
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bps": (ask - bid) / mid * 10000,
        "bid_depth_usd": sum(p * q for p, q in bids),
        "ask_depth_usd": sum(p * q for p, q in asks),
        "bids_json": json.dumps(bids, separators=(",", ":")),
        "asks_json": json.dumps(asks, separators=(",", ":")),
        "latency_ms": latency_ms,
    }


def build_clients(names):
    if ccxt is None:
        raise RuntimeError(f"ccxt is not installed ({_CCXT_ERROR}); live orderbook fetch disabled")
    return {name: getattr(ccxt, name)({"enableRateLimit": True, "timeout": 8000}) for name in names}


def collect_once(clients, symbols, store: OrderbookStore, depth=10):
    saved = errors = 0
    for exchange, client in clients.items():
        allowed = EXCHANGE_SYMBOLS.get(exchange)
        for base in symbols:
            if allowed is not None and base not in allowed:
                continue
            pair = f"{base}/USDT"
            started = time.monotonic()
            try:
                fetch_depth = max(depth, MIN_DEPTH.get(exchange, depth))
                book = client.fetch_order_book(pair, limit=fetch_depth)
                row = normalize(exchange, base, book, (time.monotonic() - started) * 1000, depth)
                if row:
                    store.add(row)
                    saved += 1
            except Exception:
                errors += 1
    store.db.commit()
    return {"saved": saved, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("once", "daemon"))
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--exchanges", nargs="+", choices=EXCHANGE_NAMES, default=list(EXCHANGE_NAMES))
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--db", type=Path, default=Path("data/quant/orderbooks.sqlite"))
    args = parser.parse_args()
    clients = build_clients(args.exchanges)
    store = OrderbookStore(args.db)
    try:
        while True:
            result = collect_once(clients, args.symbols, store, args.depth)
            store.prune(args.retention_days)
            print(json.dumps(result), flush=True)
            if args.mode == "once":
                return 0 if result["saved"] else 1
            time.sleep(max(5, args.interval))
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
