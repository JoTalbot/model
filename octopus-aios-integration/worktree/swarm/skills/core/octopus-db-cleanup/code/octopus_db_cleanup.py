#!/usr/bin/env python3
"""Bounded read-only DB cleanup analyzer.

Implements DB cleanup analysis for PostgreSQL.
Read-only by default. Never modifies database without explicit command.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def analyze_db() -> Dict[str, Any]:
    findings = []
    db_dirs = [Path(os.path.expanduser("~/agents/-Octopus")) / "data"]
    for d in db_dirs:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix in {".db", ".sqlite", ".sqlite3"}:
                size = p.stat().st_size
                findings.append({"path": str(p), "size_mb": round(size / (1024 ** 2), 2)})
    return {"databases": findings[:20], "total_found": len(findings)}


def run(_: str = "") -> Dict[str, Any]:
    db = analyze_db()
    score = 1000
    score -= min(500, len(db["databases"]) * 20)
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-db-cleanup",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "db": db,
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
