#!/usr/bin/env python3
"""P1: market context collector - Fear&Greed index + macro calendar.

Fetches:
  - Fear & Greed Index (alternative.me, free, no key): daily values history;
  - Macro calendar (faireconomy.media ff_calendar_thisweek.json, free): upcoming
    high-impact events (CPI, FOMC, NFP, rate decisions).

Appends snapshot to data/quant/market_context.jsonl and keeps latest in
data/quant/market_context_latest.json for /quant and digest.

Usage:
    python scripts/collect_market_context.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
LATEST = DATA / "quant" / "market_context_latest.json"
LOG = DATA / "quant" / "market_context.jsonl"


def get(url: str, timeout: int = 20) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    out: dict = {"ts": time.time(), "date": time.strftime("%Y-%m-%d %H:%M")}

    # Fear & Greed
    try:
        d = get("https://api.alternative.me/fng/?limit=10")
        data = d.get("data", [])
        if data:
            cur = data[0]
            out["fng"] = {
                "value": int(cur["value"]),
                "class": cur["value_classification"],
                "history": [{"value": int(x["value"]), "class": x["value_classification"]} for x in data],
            }
    except Exception as e:
        out["fng"] = {"error": str(e)}

    # Macro calendar: upcoming high-impact events (next 7 days)
    try:
        d = get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
        if isinstance(d, list):
            events = []
            now = time.time()
            for ev in d:
                try:
                    ts = float(ev.get("epoch", 0))
                except (TypeError, ValueError):
                    continue
                impact = str(ev.get("impact", "")).lower()
                if ts >= now and impact in ("high", "medium"):
                    events.append(
                        {
                            "ts": ts,
                            "date": ev.get("date", ""),
                            "time": ev.get("time", ""),
                            "title": ev.get("title", ""),
                            "country": ev.get("country", ""),
                            "impact": impact,
                        }
                    )
            events.sort(key=lambda x: x["ts"])
            out["macro"] = events[:10]
    except Exception as e:
        out["macro"] = {"error": str(e)}

    LATEST.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    with open(LOG, "a") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")

    fng = out.get("fng", {})
    if fng.get("value") is not None:
        print(f"F&G: {fng['value']} ({fng['class']})", flush=True)
    mac = out.get("macro", [])
    if isinstance(mac, list):
        print(f"макро-событий: {len(mac)}", flush=True)
        for e in mac[:3]:
            print(f"  {e['date']} {e['time']} [{e['impact']}] {e['title']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
