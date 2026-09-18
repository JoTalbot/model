#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires pandas via swarm.quant.ml_predictor (not in prod venv)
"""
Octopus Quant ML Engine - Демон инференса (Этап 2.3)

Периодически делает ML-прогноз направления цены по активам и сохраняет сигналы
в data/quant/ml_signals.json. Сигналы консультирующие (для quant_trading_engine
или человека), автоторговля не выполняется.

    python run_quant_ml_inference.py --daemon --interval 600
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from swarm.quant.ml_predictor import QuantMLPredictor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AIOS.QuantMLInference")

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
SIGNALS_FILE = DATA / "quant" / "ml_signals.json"


def run_once() -> dict:
    predictor = QuantMLPredictor()
    payload = predictor.signal_json()
    payload["generated_at"] = datetime.now(UTC).isoformat()
    SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    n = sum(1 for s in payload.get("signals", []) if s.get("ok"))
    if predictor.available:
        logger.info("ML-сигналов по %d активам -> %s", n, SIGNALS_FILE)
    else:
        logger.warning("ML-модель не обучена. Запустите Colab-ноутбук Quant ML Training. (сигналов: %d)", n)
    return payload


def run_daemon(interval: int) -> None:
    logger.info("🔮 [QuantMLInference] Демон запущен (интервал %ss)...", interval)
    while True:
        try:
            run_once()
        except Exception as e:
            logger.error("Ошибка цикла инференса: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="AIOS Quant ML Inference Daemon")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=600)
    args = ap.parse_args()

    if args.daemon:
        run_daemon(args.interval)
    else:
        print(json.dumps(run_once(), indent=2, ensure_ascii=False)[:2000])
