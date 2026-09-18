#!/usr/bin/env python3
"""Bounded read-only auditor for systemd services, restart-loops and orphan processes.

Implements instruction #07 (orphan/restart-loop checks) and vector LIVE (#05).
Read-only by default. Never restarts/stops/masks services.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

LEGITIMATE_FAILED_SERVICES = {"audit-octopus-autoheal.service", "audit-.*.service"}
LEGITIMATE_PPID1_DAEMONS = {
    "systemd-journald", "dbus-daemon", "sshd", "cron", "systemd-udevd",
    "systemd-resolved", "systemd-networkd", "systemd-timesyncd",
    "systemd-logind", "systemd-coredump", "systemd", "init",
}

SKILL_DIR = Path(__file__).resolve().parents[1]


def _run(cmd: List[str], timeout: int = 10) -> Dict[str, Any]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "rc": r.returncode, "output": (r.stdout or r.stderr or "").strip()}
    except Exception as exc:
        return {"cmd": cmd, "rc": 1, "output": f"{type(exc).__name__}: {exc}"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_failed() -> List[Dict[str, Any]]:
    data = _run(["systemctl", "list-units", "--state=failed", "--no-pager", "--plain"])
    findings: List[Dict[str, Any]] = []
    for line in data.get("output", "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            unit_name = parts[0]
            if unit_name in LEGITIMATE_FAILED_SERVICES or "audit-" in unit_name:
                continue
            findings.append({"unit": parts[0], "load": parts[1], "active": parts[2] if len(parts) > 2 else "", "sub": parts[3] if len(parts) > 3 else "", "severity": "critical" if "octopus" in parts[0] else "medium"})
    return findings


def check_restart_loops() -> List[Dict[str, Any]]:
    data = _run(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain"])
    findings: List[Dict[str, Any]] = []
    for line in data.get("output", "").splitlines():
        if "auto-restart" in line or "activating" in line:
            findings.append({"line": line, "severity": "high"})
    data2 = _run(["systemctl", "show", "-p", "NRestarts", "--type=service", "--all", "--no-pager", "--plain"])
    for line in data2.get("output", "").splitlines():
        if "=" in line:
            unit, _, val = line.partition("=")
            try:
                n = int(val.strip())
            except ValueError:
                continue
            if n > 50:
                findings.append({"unit": unit.strip(), "NRestarts": n, "severity": "critical"})
            elif n > 10:
                findings.append({"unit": unit.strip(), "NRestarts": n, "severity": "high"})
    return findings


def check_orphans() -> List[Dict[str, Any]]:
    data = _run(["ps", "-eo", "pid,ppid,user,%cpu,%mem,comm", "--no-headers"])
    findings: List[Dict[str, Any]] = []
    for line in data.get("output", "").splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        pid, ppid, user, cpu, mem, comm = parts[:6]
        if ppid != "1":
            continue
        if comm in LEGITIMATE_PPID1_DAEMONS:
            continue
        try:
            cpu_f = float(cpu)
        except ValueError:
            cpu_f = 0.0
        if cpu_f >= 90.0:
            findings.append({"pid": pid, "ppid": ppid, "comm": comm, "cpu": cpu_f, "severity": "critical"})
        elif cpu_f >= 10.0 and any(x in comm for x in ["grep", "head", "python3", "python"]):
            findings.append({"pid": pid, "ppid": ppid, "comm": comm, "cpu": cpu_f, "severity": "high"})
    return findings


def run(_: str = "") -> Dict[str, Any]:
    failed = check_failed()
    restarts = check_restart_loops()
    orphans = check_orphans()
    score = 1000
    score -= len(failed) * 50
    score -= sum(1 for f in restarts if f.get("severity") == "critical") * 30
    score -= sum(1 for f in restarts if f.get("severity") == "high") * 10
    score -= sum(1 for f in orphans if f.get("severity") == "critical") * 20
    score -= sum(1 for f in orphans if f.get("severity") == "high") * 5
    score = max(0, min(1000, score))
    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-autoheal",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "checks": {
            "failed": failed,
            "restart_loops": restarts,
            "orphans": orphans,
        },
        "summary": {
            "failed_count": len(failed),
            "restart_loop_count": len(restarts),
            "orphan_count": len(orphans),
        },
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
