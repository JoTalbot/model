#!/usr/bin/env python3
"""WebSocket orderbook depth collector for market-making research (stage 3).

Subscribes to Binance public partial-depth streams (wss://stream.binance.com:9443)
for a set of pairs and appends snapshots to data/quant/orderbooks.sqlite table
`snapshots_ws` (same schema as `snapshots`, plus a source tag). Depth and
aggTrade use TWO separate connections per pair, so trade bursts cannot flood
the depth stream or inflate the measured latency. Default: freshest snapshot
per second per pair; pairs listed in --full-pairs keep EVERY depth update
(up to ~10/s) for microstructure research. latency_ms = local receive time -
exchange event time (E from aggTrade). Read-only market data; never
authenticates or trades.

Usage:
    python scripts/collect_orderbook_ws.py [--pairs BTC ETH SOL] [--interval 1.0]
        [--db data/quant/orderbooks.sqlite]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path

import websockets

BASE_WS = "wss://stream.binance.com:9443/ws"

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))


class WSStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30.0)
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS snapshots_ws (
            ts REAL NOT NULL, source TEXT NOT NULL, symbol TEXT NOT NULL,
            bid REAL NOT NULL, ask REAL NOT NULL, mid REAL NOT NULL, spread_bps REAL NOT NULL,
            bid_depth_usd REAL NOT NULL, ask_depth_usd REAL NOT NULL,
            bids_json TEXT NOT NULL, asks_json TEXT NOT NULL, latency_ms REAL NOT NULL
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_ws_sym_ts ON snapshots_ws(symbol, ts)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS trades_ws (
            ts REAL NOT NULL, source TEXT NOT NULL, symbol TEXT NOT NULL,
            buy_vol REAL NOT NULL, sell_vol REAL NOT NULL, total_vol REAL NOT NULL,
            buy_frac REAL NOT NULL, n_trades INTEGER NOT NULL
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_trades_ws_sym_ts ON trades_ws(symbol, ts)")

    def add_batch(self, rows: list[tuple]):
        if not rows:
            return
        self.db.executemany("INSERT INTO snapshots_ws VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.db.commit()


def depth_to_json(levels) -> str:
    return json.dumps([[float(lv[0]), float(lv[1])] for lv in levels])


def level_depth_usd(levels, mid: float) -> float:
    return sum(float(lv[0]) * float(lv[1]) for lv in levels)


def depth_msg_to_snapshot(msg: dict, now_ms: float, latency_ms: float = 0.0) -> dict | None:
    """Parse a Binance depth update into a snapshot row; None when unusable.

    Partial-book depth streams carry no event time, so latency_ms is measured
    from aggTrade 'E' events (dedicated trades connection) and passed in by
    the caller.
    """

    bids, asks = msg.get("bids", []), msg.get("asks", [])
    if not bids or not asks:
        return None
    bid = float(bids[0][0])
    ask = float(asks[0][0])
    if bid <= 0 or ask <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / 2.0
    return {
        "ts": now_ms / 1000.0,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bps": (ask - bid) / mid * 1e4,
        "bid_depth_usd": level_depth_usd(bids, mid),
        "ask_depth_usd": level_depth_usd(asks, mid),
        "bids_json": depth_to_json(bids),
        "asks_json": depth_to_json(asks),
        "latency_ms": round(latency_ms, 2),
    }


def _store_snapshot(store: WSStore, source: str, pair: str, snap: dict) -> None:
    store.add_batch(
        [
            (
                snap["ts"],
                source,
                pair,
                snap["bid"],
                snap["ask"],
                snap["mid"],
                snap["spread_bps"],
                snap["bid_depth_usd"],
                snap["ask_depth_usd"],
                snap["bids_json"],
                snap["asks_json"],
                snap["latency_ms"],
            )
        ]
    )


def snapshot_latency(shared: dict, now: float, max_age: float = 10.0) -> float:
    """Latency from the trades connection, trusted only while trades flow.

    shared: {"latency_ms": float, "last_trade_seen_ts": float} updated by the
    aggTrade consumer (asyncio tasks on one loop, no locking needed).
    """

    if now - shared.get("last_trade_seen_ts", 0.0) <= max_age:
        return shared.get("latency_ms", 0.0)
    return 0.0


async def consume_one(
    ws, pair: str, interval: float, store: WSStore, shared: dict, source: str = "binance_ws", full: bool = False
) -> None:
    """Depth-only connection per pair.

    full=False: flush the freshest snapshot once per `interval` seconds.
    full=True:  append every depth update (up to ~10/s) — microstructure mode.
    Latency is taken from `shared`, maintained by the aggTrade consumer.
    """

    latest: dict | None = None
    last_ts = 0.0
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("lastUpdateId") is None:
            continue
        now = time.time()
        snap = depth_msg_to_snapshot(msg, now * 1000.0, latency_ms=snapshot_latency(shared, now))
        if snap is None:
            continue
        if full:
            _store_snapshot(store, source, pair, snap)
            continue
        latest = snap
        if latest and (now - last_ts) >= interval:
            _store_snapshot(store, source, pair, latest)
            last_ts = now
            latest = None


async def consume_trades(
    ws, pair: str, store: WSStore, shared: dict, source: str = "binance_ws", trade_interval: float = 5.0
) -> None:
    """aggTrade-only connection: measures E2E latency and flushes trade volume."""

    trades: dict[str, float] = {"buy": 0.0, "sell": 0.0, "n": 0.0}
    last_trade_ts = 0.0
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("e") != "aggTrade":
            continue
        # E is the exchange event time -> end-to-end latency of this connection
        evt = msg.get("E")
        if evt is not None:
            shared["latency_ms"] = max(0.0, time.time() * 1000.0 - float(evt))
            shared["last_trade_seen_ts"] = time.time()
        # m=True -> buyer is maker (sell aggressor)
        qty = float(msg.get("q", 0.0))
        if msg.get("m"):
            trades["sell"] += qty
        else:
            trades["buy"] += qty
        trades["n"] += 1
        now = time.time()
        if now - last_trade_ts >= trade_interval and trades["n"] > 0:
            buy, sell, n = trades["buy"], trades["sell"], trades["n"]
            total = buy + sell
            store.db.execute(
                "INSERT INTO trades_ws VALUES (?,?,?,?,?,?,?,?)",
                (now, source, pair, buy, sell, total, buy / total if total > 0 else 0.5, int(n)),
            )
            store.db.commit()
            trades = {"buy": 0.0, "sell": 0.0, "n": 0.0}
            last_trade_ts = now


async def keepalive(ws, interval: float = 20.0) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await ws.ping()
        except Exception:
            return


async def run_one(pair: str, interval: float, db_path: Path, full: bool) -> None:
    store = WSStore(db_path)
    depth_url = f"{BASE_WS}/{pair.lower()}usdt@depth20@100ms"
    trades_url = f"{BASE_WS}/{pair.lower()}usdt@aggTrade"
    shared: dict[str, float] = {"latency_ms": 0.0, "last_trade_seen_ts": 0.0}
    while True:
        try:
            async with (
                websockets.connect(depth_url, ping_interval=None) as depth_ws,
                websockets.connect(trades_url, ping_interval=None) as trades_ws,
            ):
                mode = "full" if full else f"{interval}s"
                print(f"connected {pair} [{mode}] depth+trades", flush=True)
                await asyncio.gather(
                    consume_one(depth_ws, pair, interval, store, shared, full=full),
                    consume_trades(trades_ws, pair, store, shared),
                    keepalive(depth_ws),
                    keepalive(trades_ws),
                )
        except Exception as e:
            print(f"{pair} error: {e}; reconnect in 5s", flush=True)
            await asyncio.sleep(5)


async def run(pairs: list[str], interval: float, db_path: Path, full_pairs: list[str] | None = None) -> None:
    full_set = set(full_pairs or [])
    await asyncio.gather(*(run_one(p, interval, db_path, p in full_set) for p in pairs))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--db", type=Path, default=DATA / "quant" / "orderbooks.sqlite")
    ap.add_argument(
        "--full-pairs", nargs="*", default=["BTC", "ETH"], help="pairs keeping every depth update (microstructure mode)"
    )
    args = ap.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args.pairs, args.interval, args.db, args.full_pairs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
