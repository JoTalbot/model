#!/usr/bin/env python3
"""
AIOS Quant ML Engine - Сбор рыночных данных с 5 бирж (Этап 2.1)

Собирает тики/свечи/глубину стакана с публичных API:
  - Binance, Bybit, OKX, Kraken  (через ccxt)
  - Uniswap V3                    (через ccxt.uniswapv3 / The Graph)

Хранение: data/quant/<SYMBOL>/<EXCHANGE>/*.csv
Выгрузка для Colab: data/quant/export/latest.tar.gz

Поддерживает расширенный набор ликвидных крипто-активов (по 4 на ликвидность на всех биржах).

Использование:
    from swarm.quant.data_collector import MarketDataCollector
    c = MarketDataCollector()
    c.collect_ohlcv_all()
    c.export_for_colab()
"""

from __future__ import annotations

import csv
import json
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import resolve_data_dir

try:
    import ccxt

    _CCXT_ERROR = None
except ImportError as e:  # prod venv has no ccxt
    ccxt = None
    _CCXT_ERROR = e

QUANT_DIR = resolve_data_dir() / "quant"
EXPORT_DIR = QUANT_DIR / "export"

# --- 24 актива: base/quote, где BASE - актив, QUOTE - USDT (или USD на Kraken) --
# Выбираем самые ликвидные; на Kraken нет USDT-пар для всех, поэтому для него
# используем USD/USDC пары где это доступно (обрабатывается в _pair_per_exchange).
DEFAULT_SYMBOLS = [
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "LINK",
    "DOT",
    "POL",
    "LTC",
    "TRX",
    "ATOM",
    "UNI",
    "ETC",
    "FIL",
    "APT",
    "NEAR",
    "ARB",
    "OP",
    "SUI",
    "TIA",
    "SEI",
    "TON",
    "INJ",
    "KAS",
    "RENDER",
    "FET",
    "WIF",
    "BONK",
    "PEPE",
    "SHIB",
]

# Какие биржи обрабатываем и за каким "exchange id" ccxt.
# Uniswap V3 НЕ поддерживается ccxt -> обрабатывается отдельным модулем
# aios_core/quant/uniswap_v3.py через The Graph subgraph.
EXCHANGE_IDS = (
    "binance",
    "bybit",
    "okx",
    "kraken",
    "coinbase",
    "kucoin",
    "bitfinex",
    "bitstamp",
    "mexc",
)

# По умолчанию собираем OHLCV. Depth (стакан) - тяжёлый, собираем реже.
TIMEFRAMES = ["1h", "4h", "1d"]

LOG_TAG = "[QuantDataCollector]"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class MarketDataCollector:
    def __init__(
        self,
        symbols: list[str] | None = None,
        exchanges: list[str] | None = None,
        quant_dir: Path | None = None,
    ):
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.exchange_names = exchanges or list(EXCHANGE_IDS)
        self.quant_dir = Path(quant_dir or QUANT_DIR)
        self.export_dir = self.quant_dir / "export"
        self.quant_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

        self._clients: dict[str, Any] = {}
        self._init_clients()

    def _init_clients(self) -> None:
        if ccxt is None:
            raise RuntimeError(f"ccxt is not installed ({_CCXT_ERROR}); live market fetch disabled")
        for name in self.exchange_names:
            cls = getattr(ccxt, name, None)
            if cls is None:
                continue
            client = cls({"enableRateLimit": True, "timeout": 20000})
            self._clients[name] = client

    # ---------------------------------------------------------- pairing -----
    def _pair_for(self, exchange: str, base: str) -> str | None:
        """Вернуть торговую пару BASE/QUOTE для конкретной биржи."""
        quote = "USDT"
        # Kraken: большинство пар в USDT нет -> USDC/USD
        if exchange == "kraken":
            quote = "USD"
        pair = f"{base}/{quote}"
        try:
            markets = self._clients[exchange].load_markets()
        except Exception:
            markets = {}
        if pair in markets:
            return pair
        # попробуем альтернативные кавычки
        for alt in ["USDC", "USD", "USDT"] if exchange != "kraken" else ["USDT", "USDC"]:
            p = f"{base}/{alt}"
            if p in markets:
                return p
        return None

    # ------------------------------------------------------------ single ----
    def _fetch_ohlcv(self, exchange: str, pair: str, timeframe: str, limit: int = 500) -> list[list]:
        """Fetch closed candles; paginate requests larger than exchange page limits."""
        try:
            client = self._clients[exchange]
            if limit <= 1000:
                return client.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
            timeframe_ms = int(client.parse_timeframe(timeframe) * 1000)
            closed_before = int(time.time() * 1000 // timeframe_ms) * timeframe_ms
            since = closed_before - limit * timeframe_ms
            candles: dict[int, list] = {}
            while len(candles) < limit and since < closed_before:
                page_limit = min(1000, limit - len(candles))
                page = client.fetch_ohlcv(pair, timeframe=timeframe, since=since, limit=page_limit) or []
                if not page:
                    break
                previous_since = since
                for row in page:
                    timestamp = int(row[0])
                    if timestamp < closed_before:
                        candles[timestamp] = row
                since = max(int(row[0]) for row in page) + timeframe_ms
                if since <= previous_since:
                    break
            return [candles[key] for key in sorted(candles)][-limit:]
        except Exception as e:
            print(f"{LOG_TAG} [WARN] {exchange}/{pair}/{timeframe}: {e}")
            return []

    def _fetch_order_book(self, exchange: str, pair: str, limit: int = 100) -> dict | None:
        try:
            client = self._clients[exchange]
            return client.fetch_order_book(pair, limit=limit)
        except Exception as e:
            print(f"{LOG_TAG} [WARN] orderbook {exchange}/{pair}: {e}")
            return None

    # ------------------------------------------------------------ storage ----
    def _save_csv(self, path: Path, rows: list[list], header: list[str]) -> None:
        """Merge OHLCV by timestamp so short daemon refreshes preserve backfill."""
        path.parent.mkdir(parents=True, exist_ok=True)
        merged: dict[int, list] = {}
        if path.exists():
            try:
                with path.open(newline="", encoding="utf-8") as stream:
                    for row in csv.reader(stream):
                        if row and row[0] != header[0]:
                            merged[int(float(row[0]))] = row
            except (OSError, ValueError):
                merged = {}
        for row in rows:
            if row:
                merged[int(float(row[0]))] = row
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(merged[key] for key in sorted(merged))

    # ------------------------------------------------------------ collect ----
    def collect_ohlcv(
        self,
        base: str,
        timeframe: str = "1h",
        limit: int = 500,
        save: bool = True,
    ) -> dict:
        """Собрать OHLCV для актива по всем биржам. Возвращает {exchange: rows}."""
        result: dict[str, list] = {}
        header = ["timestamp_ms", "open", "high", "low", "close", "volume", "collected_at"]
        for ex in self.exchange_names:
            if ex not in self._clients:
                continue
            pair = self._pair_for(ex, base)
            if not pair:
                print(f"{LOG_TAG} [SKIP] {ex}: пара для {base} не найдена")
                continue
            rows = self._fetch_ohlcv(ex, pair, timeframe, limit=limit)
            if not rows:
                continue
            out_rows = [[r[0], r[1], r[2], r[3], r[4], r[5], _utc_now()] for r in rows]
            result[ex] = out_rows
            if save:
                fname = f"{base}_{timeframe}.csv"
                self._save_csv(self.quant_dir / base / ex / fname, out_rows, header)
        return result

    def collect_ohlcv_all(self, timeframe: str = "1h", limit: int = 500, save: bool = True) -> dict:
        """Собрать OHLCV по всем активам."""
        summary = {}
        for base in self.symbols:
            res = self.collect_ohlcv(base, timeframe=timeframe, limit=limit, save=save)
            summary[base] = {k: len(v) for k, v in res.items()}
            time.sleep(1)  # rate-limit вежливость
        self._write_manifest(summary)
        return summary

    def collect_orderbooks(self, base: str, limit: int = 100, save: bool = True) -> dict:
        """Собрать глубину стакана для актива по биржам."""
        result: dict[str, dict] = {}
        for ex in self.exchange_names:
            if ex not in self._clients:
                continue
            pair = self._pair_for(ex, base)
            if not pair:
                continue
            ob = self._fetch_order_book(ex, pair, limit=limit)
            if not ob:
                continue
            result[ex] = {
                "pair": pair,
                "timestamp": _utc_now(),
                "bids_depth": sum(a[1] for a in ob.get("bids", [])[:5]),
                "asks_depth": sum(a[1] for a in ob.get("asks", [])[:5]),
                "bids_count": len(ob.get("bids", [])),
                "asks_count": len(ob.get("asks", [])),
                "best_bid": ob["bids"][0][0] if ob.get("bids") else None,
                "best_ask": ob["asks"][0][0] if ob.get("asks") else None,
            }
            if save:
                fname = f"{base}_orderbook.json"
                (self.quant_dir / base / ex).mkdir(parents=True, exist_ok=True)
                with open(self.quant_dir / base / ex / fname, "w", encoding="utf-8") as f:
                    json.dump(result[ex], f, indent=2)
        return result

    # ------------------------------------------------------------ manifest ---
    def _write_manifest(self, summary: dict) -> None:
        manifest = {
            "generated_at": _utc_now(),
            "symbols": self.symbols,
            "exchanges": self.exchange_names,
            "counts": summary,
        }
        with open(self.quant_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    # ------------------------------------------------------------ export -----
    def export_for_colab(self) -> str | None:
        """Упаковать данные в tar.gz для выгрузки в Colab."""
        archive = self.export_dir / "latest.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(self.quant_dir.rglob("*")):
                if path.is_file() and self.export_dir not in path.parents and path.name != "latest.tar.gz":
                    tar.add(path, arcname=str(path.relative_to(self.quant_dir)))
        return str(archive)


# --- CLI ----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="AIOS Quant Market Data Collector")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--exchanges", nargs="*", default=None)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--orderbooks", action="store_true", help="Дополнительно собрать стаканы")
    ap.add_argument("--export", action="store_true", help="Упаковать данные для Colab")
    args = ap.parse_args()

    c = MarketDataCollector(symbols=args.symbols, exchanges=args.exchanges)
    print(f"{LOG_TAG} Сбор OHLCV ({args.timeframe}, limit={args.limit})...")
    summary = c.collect_ohlcv_all(timeframe=args.timeframe, limit=args.limit)
    for base, cnt in summary.items():
        print(f"  {base}: {cnt}")
    if args.orderbooks:
        print(f"{LOG_TAG} Сбор стаканов...")
        for base in args.symbols or DEFAULT_SYMBOLS:
            c.collect_orderbooks(base)
    if args.export:
        path = c.export_for_colab()
        print(f"{LOG_TAG} Экспорт для Colab: {path}")
