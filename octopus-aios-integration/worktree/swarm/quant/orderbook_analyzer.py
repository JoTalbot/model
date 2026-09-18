"""
AIOS Orderbook Depth & Liquidation Wall Analyzer
Анализирует глубину стакана ордеров (Bid/Ask Orderbook Imbalance) с 60s кэшированием.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

logger = logging.getLogger("AIOS.Orderbook")

_ORDERBOOK_CACHE: dict[str, dict[str, Any]] = {}


class AIOSOrderbookAnalyzer:
    """Модуль анализа глубины стакана лимитных ордеров."""

    @classmethod
    def _clean_symbol(cls, raw_symbol: str) -> str:
        clean = raw_symbol.upper()
        for p in ["KRAKEN_", "BINANCE_", "BYBIT_", "OKX_", "UNISWAP_V3_"]:
            clean = clean.replace(p, "")
        for s in ["USDT", "USDC", "USD"]:
            if clean.endswith(s) and len(clean) > len(s):
                clean = clean[: -len(s)]
        return clean

    @classmethod
    def analyze_orderbook(cls, symbol: str = "BTC") -> dict[str, Any]:
        """Запрашивает глубину стакана (топ 20 ордеров) с 60-секундным кэшем."""
        clean_sym = cls._clean_symbol(symbol)
        now = time.time()

        if clean_sym in _ORDERBOOK_CACHE:
            cached = _ORDERBOOK_CACHE[clean_sym]
            if now - cached.get("timestamp", 0) < 60:
                return cached.get("data", {})

        url = f"https://api.binance.com/api/v3/depth?symbol={clean_sym}USDT&limit=20"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                bids = data.get("bids", [])
                asks = data.get("asks", [])

                total_bid_usd = sum(float(b[0]) * float(b[1]) for b in bids)
                total_ask_usd = sum(float(a[0]) * float(a[1]) for a in asks)

                imbalance_ratio = round(total_bid_usd / max(1.0, total_ask_usd), 2)
                best_bid_wall = max(bids, key=lambda x: float(x[1])) if bids else ["0", "0"]
                best_ask_wall = max(asks, key=lambda x: float(x[1])) if asks else ["0", "0"]

                res = {
                    "symbol": clean_sym,
                    "bid_ask_imbalance_ratio": imbalance_ratio,
                    "total_bids_usd": round(total_bid_usd, 2),
                    "total_asks_usd": round(total_ask_usd, 2),
                    "bid_wall_price": float(best_bid_wall[0]),
                    "ask_wall_price": float(best_ask_wall[0]),
                    "status": "BUY_WALL_SUPPORT"
                    if imbalance_ratio > 1.25
                    else ("SELL_WALL_RESISTANCE" if imbalance_ratio < 0.8 else "BALANCED"),
                }
                _ORDERBOOK_CACHE[clean_sym] = {"timestamp": now, "data": res}
                return res
        except Exception:
            res = {"symbol": clean_sym, "bid_ask_imbalance_ratio": 1.0, "status": "BALANCED"}
            _ORDERBOOK_CACHE[clean_sym] = {"timestamp": now, "data": res}
            return res


if __name__ == "__main__":
    t0 = time.time()
    print("BTC:", AIOSOrderbookAnalyzer.analyze_orderbook("BTC"))
    print("Time taken:", round(time.time() - t0, 3), "s")
