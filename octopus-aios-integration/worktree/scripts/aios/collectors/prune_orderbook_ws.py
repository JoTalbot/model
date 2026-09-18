#!/usr/bin/env python3
"""Retention pruning for the orderbook WebSocket research database.

Policy (owner-approved 2026-08-17):
- snapshots_ws: keep raw 1 Hz rows for RAW_DAYS; for the window
  [RAW_DAYS, KEEP_DAYS) keep one representative row per symbol per minute
  (MIN(rowid) of the minute bucket) and delete the rest; delete everything
  older than KEEP_DAYS.
- trades_ws: delete rows older than KEEP_DAYS (no downsampling).

Read-only for trading: never touches orders or portfolios. Safe to run
concurrently with scripts/collect_orderbook_ws.py (WAL + busy_timeout).

Usage:
    python scripts/prune_orderbook_ws.py [--db data/quant/orderbooks.sqlite]
        [--raw-days 7] [--keep-days 60] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


def prune(db_path: Path, raw_days: int, keep_days: int, *, dry_run: bool = False) -> dict[str, int]:
    if raw_days <= 0 or keep_days <= raw_days:
        raise SystemExit(f"invalid window: 0 < raw_days({raw_days}) < keep_days({keep_days})")
    now = time.time()
    raw_cut = now - raw_days * 86400.0
    keep_cut = now - keep_days * 86400.0

    con = sqlite3.connect(db_path, timeout=30.0)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    stats: dict[str, int] = {}

    # snapshots_ws: minute-downsample the middle window, hard-delete the tail.
    con.execute(
        """
        DELETE FROM snapshots_ws
        WHERE ts >= :keep_cut AND ts < :raw_cut
          AND rowid NOT IN (
              SELECT MIN(rowid) FROM snapshots_ws
              WHERE ts >= :keep_cut AND ts < :raw_cut
              GROUP BY symbol, CAST((ts - :keep_cut) / 60.0 AS INTEGER)
          )
        """,
        {"keep_cut": keep_cut, "raw_cut": raw_cut},
    )
    stats["snapshots_ws_downsampled"] = con.total_changes
    con.execute("DELETE FROM snapshots_ws WHERE ts < :keep_cut", {"keep_cut": keep_cut})
    stats["snapshots_ws_deleted_tail"] = con.total_changes - stats["snapshots_ws_downsampled"]

    # trades_ws: hard-delete the tail only.
    con.execute("DELETE FROM trades_ws WHERE ts < :keep_cut", {"keep_cut": keep_cut})
    stats["trades_ws_deleted_tail"] = (
        con.total_changes - stats["snapshots_ws_downsampled"] - stats["snapshots_ws_deleted_tail"]
    )

    if not dry_run:
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    else:
        con.rollback()
    con.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune orderbook ws research DB")
    parser.add_argument("--db", type=Path, default=Path("data/quant/orderbooks.sqlite"))
    parser.add_argument("--raw-days", type=int, default=7)
    parser.add_argument("--keep-days", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"SKIP: db not found: {args.db}")
        return 0
    stats = prune(args.db, args.raw_days, args.keep_days, dry_run=args.dry_run)
    mode = "DRY-RUN" if args.dry_run else "PRUNED"
    print(f"{mode} {args.db}: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
