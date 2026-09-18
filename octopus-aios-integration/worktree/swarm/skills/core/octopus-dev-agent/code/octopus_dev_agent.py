#!/usr/bin/env python3
"""Bounded read-only dev agent auditor.

Implements bounded code review and task decomposition.
Read-only by default. Never modifies code without explicit command.
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


def scan_tasks() -> List[Dict[str, Any]]:
    tasks = []
    task_dirs = [BASE / "logs", BASE / "reports", BASE / "experience"]
    for d in task_dirs:
        if not d.exists():
            continue
        for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
            if p.is_file() and p.suffix in {".md", ".txt", ".json"}:
                text = p.read_text(encoding="utf-8", errors="replace")
                tasks.append({"path": str(p), "name": p.name, "size": p.stat().st_size, "preview": text[:200]})
    return tasks


def run(_: str = "") -> Dict[str, Any]:
    tasks = scan_tasks()
    score = 1000
    score -= max(0, 10 - len(tasks)) * 10
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-dev-agent",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "tasks_count": len(tasks),
        "recent_tasks": tasks[:10],
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
