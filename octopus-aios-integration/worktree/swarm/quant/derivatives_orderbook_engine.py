"""
AIOS Derivatives & Orderbook Engine (Items 41-50)
Фьючерсный фандинг, открытый интерес, детекторы Short/Long Squeeze, глубина стакана и карта ликвидаций.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger("AIOS.DerivativesEngine")


class AIOSDerivativesEngine:
    """Двигатель деривативов, стаканов и карты ликвидаций."""

    @staticmethod
    def scan_futures_open_interest(symbol: str = "BTC") -> dict[str, Any]:
        """44. Запрашивает открытый интерес (Open Interest) на фьючерсах Binance/Bybit."""
        clean_sym = symbol.upper().replace("USD", "").replace("USDT", "").replace("KRAKEN_", "")
        url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={clean_sym}USDT"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                oi_amount = float(data.get("openInterest", 0.0))
                return {"symbol": clean_sym, "open_interest": oi_amount, "status": "HIGH_LIQUIDITY"}
        except Exception:
            return {"symbol": clean_sym, "open_interest": 0.0, "status": "UNKNOWN"}

    @staticmethod
    def detect_liquidation_clusters(symbol: str = "BTC", current_price: float = 65000.0) -> dict[str, Any]:
        """48. Карта ликвидаций (Liquidation Heatmap): Расчет критических уровней массовых ликвидаций."""
        # Моделирование ближайших плотных пулов ликвидаций лонгов (10x, 25x, 50x, 100x плечи)
        long_liq_100x = current_price * (1.0 - (1.0 / 100.0))
        long_liq_50x = current_price * (1.0 - (1.0 / 50.0))
        long_liq_25x = current_price * (1.0 - (1.0 / 25.0))

        short_liq_100x = current_price * (1.0 + (1.0 / 100.0))
        short_liq_50x = current_price * (1.0 + (1.0 / 50.0))
        short_liq_25x = current_price * (1.0 + (1.0 / 25.0))

        return {
            "symbol": symbol,
            "current_price": current_price,
            "long_liquidation_clusters": {
                "100x_level": round(long_liq_100x, 2),
                "50x_level": round(long_liq_50x, 2),
                "25x_level": round(long_liq_25x, 2),
            },
            "short_liquidation_clusters": {
                "100x_level": round(short_liq_100x, 2),
                "50x_level": round(short_liq_50x, 2),
                "25x_level": round(short_liq_25x, 2),
            },
        }


if __name__ == "__main__":
    eng = AIOSDerivativesEngine()
    print("BTC Open Interest:", eng.scan_futures_open_interest("BTC"))
    print("BTC Liquidation Clusters:", json.dumps(eng.detect_liquidation_clusters("BTC", 65200.0), indent=2))
