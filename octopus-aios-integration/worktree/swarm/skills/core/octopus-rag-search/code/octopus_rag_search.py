#!/usr/bin/env python3
"""Bounded read-only RAG search health checker.

Implements RAG search health checks.
Read-only by default. Never modifies index without explicit command.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(url: str, timeout: int = 5) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "status": r.status, "data": json.loads(r.read().decode())}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def check_rag() -> Dict[str, Any]:
    base = "http://127.0.0.1:9560"
    health = _get(base + "/healthz")
    if not health["ok"]:
        return health
    search = _get(base + "/search?q=test&limit=1")
    return {"health": health, "search_probe": search}


def run(_: str = "") -> Dict[str, Any]:
    rag = check_rag()
    score = 1000
    if not rag.get("ok"):
        score -= 200
    elif not rag.get("health", {}).get("ok"):
        score -= 100
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-rag-search",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "rag": rag,
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
