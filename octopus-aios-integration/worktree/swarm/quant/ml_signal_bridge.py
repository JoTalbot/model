#!/usr/bin/env python3
"""
AIOS Quant ML - Консультирующий мост ML-сигналов (улучшение P0-3)

Читает ML-прогнозы (data/quant/ml_signals.json), созданные демоном
aios-quant-ml-inference, и предоставляет их как КОНСУЛЬТИРУЮЩИЙ источник для
quant_trading_engine / отчётов / дашборда. Никакой автоторговли.

Интеграция с QuantSignalEngine:
    from swarm.quant.ml_signal_bridge import MLSignalBridge
    bridge = MLSignalBridge()
    strong = bridge.strong_signals(min_prob=0.6)   # сильные консультирующие сигналы

Безопасность: мост только читает данные; не инициирует сделки.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))
SIGNALS_FILE = DATA / "quant" / "ml_signals.json"

LOG_TAG = "[MLSignalBridge]"


class MLSignalBridge:
    """Консультирующий доступ к ML-сигналам (read-only)."""

    def __init__(self, signals_file: Path | None = None):
        self.signals_file = Path(signals_file or SIGNALS_FILE)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.signals_file.exists():
            return {"model_available": False, "signals": [], "generated_at": None}
        try:
            return json.loads(self.signals_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"{LOG_TAG} [WARN] Не удалось прочитать сигналы: {e}")
            return {"model_available": False, "signals": [], "generated_at": None}

    @property
    def available(self) -> bool:
        return bool(self._data.get("model_available")) and bool(
            self._data.get("signals")
        )

    def all_signals(self) -> list[dict]:
        return [s for s in self._data.get("signals", []) if s.get("ok")]

    def strong_signals(self, min_prob: float = 0.6) -> dict:
        """Сильные консультирующие сигналы (вероятность выше порога)."""
        up, down = [], []
        for s in self.all_signals():
            p_up = s.get("prob_up", 0.5)
            if p_up >= min_prob:
                up.append(s)
            elif p_up <= 1 - min_prob:
                down.append(s)
        return {
            "bullish": sorted(up, key=lambda x: -x["prob_up"]),
            "bearish": sorted(down, key=lambda x: x["prob_up"]),
        }

    def top_momentum(self, n: int = 5) -> list[dict]:
        """Топ активов по ML-направленности (spread)."""
        scored = []
        for s in self.all_signals():
            spread = abs(s.get("prob_up", 0.5) - 0.5) * 2  # 0..1
            scored.append({**s, "ml_spread": round(spread, 4)})
        scored.sort(key=lambda x: x["ml_spread"], reverse=True)
        return scored[:n]

    def summary(self) -> dict:
        strong = self.strong_signals(min_prob=0.6)
        return {
            "available": self.available,
            "generated_at": self._data.get("generated_at"),
            "total": len(self.all_signals()),
            "bullish_strong": len(strong["bullish"]),
            "bearish_strong": len(strong["bearish"]),
            "top_momentum": [s["symbol"] for s in self.top_momentum(3)],
        }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--strong", type=float, default=0.6)
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    b = MLSignalBridge()
    print(json.dumps(b.summary(), indent=2, ensure_ascii=False))
    print("\n--- Сильные сигналы ---")
    strong = b.strong_signals(min_prob=args.strong)
    print("BULLISH:", [s["symbol"] for s in strong["bullish"]])
    print("BEARISH:", [s["symbol"] for s in strong["bearish"]])
    print("\n--- Топ-моментум ---")
    for s in b.top_momentum(args.top):
        print(
            f"  {s['symbol']}: {'UP' if s['direction'] == 'UP' else 'DOWN'} spread={s['ml_spread']}"
        )
