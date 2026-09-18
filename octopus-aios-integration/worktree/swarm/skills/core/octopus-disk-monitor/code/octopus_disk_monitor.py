#!/usr/bin/env python3
"""Bounded read-only disk monitor.

Implements disk space monitoring and forecasting.
Read-only by default. Never modifies data or cleans up without explicit command.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_disk() -> List[Dict[str, Any]]:
    results = []
    for part in ["/", "/tmp", "/var"]:
        try:
            usage = shutil.disk_usage(part)
            percent = (usage.used / usage.total) * 100
            results.append({
                "path": part,
                "total_gb": round(usage.total / (1024 ** 3), 1),
                "used_gb": round(usage.used / (1024 ** 3), 1),
                "free_gb": round(usage.free / (1024 ** 3), 1),
                "percent": round(percent, 1),
            })
        except Exception as exc:
            results.append({"path": part, "error": str(exc)})
    return results


def run(_: str = "") -> Dict[str, Any]:
    disks = check_disk()
    score = 1000
    for d in disks:
        if "percent" in d:
            if d["percent"] >= 90:
                score -= 200
            elif d["percent"] >= 75:
                score -= 50
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-disk-monitor",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "disks": disks,
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
