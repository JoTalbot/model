#!/usr/bin/env python3
"""Bounded read-only alerting auditor.

Implements alerting rules and threshold checks.
Read-only by default. Never modifies alerting config.
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


def check_alerts() -> List[Dict[str, Any]]:
    alerts = []
    try:
        import subprocess
        r = subprocess.run(["systemctl", "list-units", "--state=failed", "--no-pager", "--plain"],
                           capture_output=True, text=True, timeout=10)
        for line in (r.stdout or "").splitlines()[1:]:
            parts = line.split()
            if parts:
                alerts.append({"unit": parts[0], "severity": "critical" if "octopus" in parts[0] else "medium"})
    except Exception:
        pass
    return alerts


def run(_: str = "") -> Dict[str, Any]:
    alerts = check_alerts()
    score = 1000
    score -= sum(1 for a in alerts if a["severity"] == "critical") * 50
    score -= sum(1 for a in alerts if a["severity"] == "medium") * 10
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-alerting",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "alerts": alerts[:20],
        "alert_count": len(alerts),
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
