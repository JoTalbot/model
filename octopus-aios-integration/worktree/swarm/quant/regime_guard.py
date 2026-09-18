"""Режимный kill-guard для бумажных входов Directional v2.

В режимах CRASH/PANIC входы блокируются (сохранение капитала), в остальных —
разрешены. Читает data/reports/market_regime_latest.json (пишется ежедневно
scripts/quant_regime_engine.py). Fail-open: при отсутствии/повреждении файла
guard НЕ блокирует (текущее поведение сохраняется).
"""

from __future__ import annotations

import json
from pathlib import Path

BLOCK_REGIMES = {"CRASH", "PANIC"}


def current_regime(path: str) -> str | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        value = str(data.get("regime") or "").strip().upper()
        return value or None
    except (OSError, ValueError, TypeError):
        return None


def crash_kill_active(path: str) -> bool:
    return current_regime(path) in BLOCK_REGIMES
