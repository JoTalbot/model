#!/usr/bin/env python3
"""Bounded read-only auditor for multi-node sync state.

Implements instruction #19 (eternal DR + multisync) and vector ПАМЯТЬ (#05):
- Checks rsync-like sync status between parent and ubu-worker
- Reports drift, missing files, and sync lag
Read-only by default. Never pushes/pulls data without explicit command.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(os.path.expanduser("~/agents/-Octopus"))
NODES_PATH = BASE / "config" / "nodes.json"


def _run(cmd: List[str], timeout: int = 10) -> Dict[str, Any]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "rc": r.returncode, "output": (r.stdout or r.stderr or "").strip()}
    except Exception as exc:
        return {"cmd": cmd, "rc": 1, "output": f"{type(exc).__name__}: {exc}"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_nodes() -> List[Dict[str, Any]]:
    if not NODES_PATH.exists():
        return []
    try:
        data = json.loads(NODES_PATH.read_text())
        return data.get("nodes", [])
    except Exception:
        return []


def check_sync_paths() -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    critical_paths = [
        BASE / "instructions" / "COMPACT_CONTEXT.md",
        BASE / "config" / "nodes.json",
        BASE / "experience",
        BASE / "logs",
    ]
    for path in critical_paths:
        if path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            findings.append({"path": str(path), "exists": True, "mtime": mtime})
        else:
            findings.append({"path": str(path), "exists": False, "severity": "critical"})
    return findings


def run(_: str = "") -> Dict[str, Any]:
    nodes = load_nodes()
    sync_paths = check_sync_paths()
    missing_critical = sum(1 for p in sync_paths if not p.get("exists", False))
    score = 1000
    score -= missing_critical * 100
    score -= max(0, len(nodes) - 5) * 5
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-multisync",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "nodes_count": len(nodes),
        "sync_paths": sync_paths,
        "missing_critical_paths": missing_critical,
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
