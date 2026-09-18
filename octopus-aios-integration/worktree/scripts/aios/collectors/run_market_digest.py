#!/usr/bin/env python3
"""
Дневной снапшот рынка OLX по нишам авторазборок и б/у запчастей ВАЗ/ГАЗель.
Считает n/min/median/max по активным объявлениям каждого запроса коллектора,
сохраняет в data/market_snapshots.json (хранит 30 дней) — для трендов в брифинге.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import statistics
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
DB = DATA / "olx_http.sqlite"
SNAPS = DATA / "market_snapshots.json"


def snapshot() -> dict:
    out = {}
    try:
        con = sqlite3.connect(DB)
        rows = con.execute("select query, price_value from ads where active=1 and price_value>0")
        by: dict[str, list[float]] = {}
        for q, p in rows:
            by.setdefault(q, []).append(float(p))
        for q, prices in by.items():
            prices.sort()
            out[q] = {"n": len(prices), "min": prices[0], "median": round(statistics.median(prices)), "max": prices[-1]}
    except Exception:
        pass
    return out


def save() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    data = {}
    with contextlib.suppress(Exception):
        data = json.loads(SNAPS.read_text(encoding="utf-8"))
    data[today] = snapshot()
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    data = {k: v for k, v in data.items() if k >= cutoff}
    SNAPS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def trend_lines() -> list[str]:
    """Строки для брифинга: медиана по нише и движение к прошлому снапшоту."""
    try:
        data = json.loads(SNAPS.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not data:
        return []
    dates = sorted(data.keys())
    today = dates[-1]
    prev = data[dates[-2]] if len(dates) > 1 else None
    lines = []
    for q, cur in sorted(data[today].items(), key=lambda kv: -kv[1]["n"]):
        med = cur["median"]
        arrow = ""
        if prev and q in prev and prev[q]["median"]:
            old = prev[q]["median"]
            if old and med != old:
                pct = int((med - old) / old * 100)
                arrow = f" ({'+' if pct > 0 else ''}{pct}% за сутки)"
        lines.append(f"• {q}: медиана {med} грн, n={cur['n']}{arrow}")
    return lines


def main() -> int:
    save()
    print(json.dumps(trend_lines(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
