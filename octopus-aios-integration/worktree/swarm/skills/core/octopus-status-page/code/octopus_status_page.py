#!/usr/bin/env python3
"""Bounded read-only status page generator.

Implements status page generation from health checks.
Read-only by default. Never modifies system state.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(os.path.expanduser("~/agents/-Octopus"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_status() -> Dict[str, Any]:
    services = []
    try:
        import subprocess
        r = subprocess.run(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain"],
                           capture_output=True, text=True, timeout=10)
        for line in (r.stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                services.append({"unit": parts[0], "load": parts[1], "active": parts[2], "sub": parts[3]})
    except Exception:
        pass
    return {"services": services[:50], "total": len(services)}


def run(_: str = "") -> Dict[str, Any]:
    status = collect_status()
    score = 1000
    failed = sum(1 for s in status["services"] if s.get("active") == "failed")
    score -= failed * 20
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-status-page",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "services": status["services"],
        "failed_count": failed,
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
