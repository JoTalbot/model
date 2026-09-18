#!/usr/bin/env python3
"""Bounded read-only CAS API auditor.

Implements CAS API health and stats checks.
Read-only by default. Never modifies CAS data.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(os.path.expanduser("~/agents/-Octopus"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(url: str, timeout: int = 5) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "status": r.status, "data": json.loads(r.read().decode())}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def check_cas() -> Dict[str, Any]:
    base = "http://127.0.0.1:9540"
    health = _get(base + "/healthz")
    if not health["ok"]:
        return health
    stats = _get(base + "/cas/stats")
    manifest = _get(base + "/cas/manifest")
    return {
        "health": health,
        "stats": stats,
        "manifest": manifest,
        "reachable": True,
    }


def run(_: str = "") -> Dict[str, Any]:
    cas = check_cas()
    score = 1000
    if not cas.get("reachable"):
        score -= 200
    elif not cas.get("health", {}).get("ok"):
        score -= 100
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-cas-api",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "cas": cas,
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
