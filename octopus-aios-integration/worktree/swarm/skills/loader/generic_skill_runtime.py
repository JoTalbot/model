#!/usr/bin/env python3
"""Generic bounded runtime for Octopus skills converted from stubs.

The runtime is intentionally read-only by default. It turns a SKILL.md from a
static instruction into an executable skill contract: classify, inspect, report,
and recommend next bounded improvements. Destructive actions must be implemented
as explicit first-class skills with consent gates.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(os.path.expanduser("~/agents/-Octopus"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_cmd(args: List[str], timeout: int = 8) -> Dict[str, Any]:
    """Run an allowlisted read-only command and capture a small output sample."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or r.stderr or "").strip()
        return {"cmd": args, "rc": r.returncode, "output": out[:1200]}
    except FileNotFoundError:
        return {"cmd": args, "rc": 127, "output": "command_not_found"}
    except subprocess.TimeoutExpired:
        return {"cmd": args, "rc": 124, "output": "timeout"}
    except Exception as e:  # pragma: no cover - defensive
        return {"cmd": args, "rc": 1, "output": f"{type(e).__name__}: {e}"[:1200]}


def read_skill(skill_dir: Path) -> Dict[str, str]:
    skill_file = skill_dir / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8", errors="replace") if skill_file.exists() else ""
    name = skill_dir.name
    description = ""
    m = re.search(r"^name:\s*(.+)$", text, re.M)
    if m:
        name = m.group(1).strip().strip('"\'')
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    if m:
        description = m.group(1).strip().strip('"\'')
    if not description:
        m = re.search(r"##\s*Описани[ея]\s*\n(.+?)(?:\n##|\Z)", text, re.S)
        if m:
            description = " ".join(m.group(1).strip().split())[:500]
    return {"name": name, "description": description, "text": text}


def classify(name: str, text: str) -> List[str]:
    pre_algorithm = text.split("## Алгоритм", 1)[0]
    hay = f"{name}\n{pre_algorithm[:3000]}".lower()
    groups = {
        "telegram": ["telegram", "tg", "notification", "alert"],
        "aws_cost": ["aws", "cost", "free-tier", "budget"],
        "disk": ["disk", "cleanup", "janitor", "archive", "rotate", "storage"],
        "memory": ["memory", "cas", "pack", "merkle", "backup", "restore", "dr", "snapshot", "ipfs"],
        "api": ["api", "health", "dashboard", "rag", "ingest", "events", "http"],
        "systemd": ["service", "systemd", "watchdog", "guardian", "autoheal"],
        "docker_swarm": ["docker", "swarm", "node", "federation", "reproduction", "p2p"],
        "security": ["security", "crypto", "secret", "port", "policy", "consent"],
        "llm_ai": ["llm", "ai", "rag", "model", "skill", "reasoning", "evolution"],
        "audio_image": ["audio", "voice", "whisper", "image", "clip", "ocr"],
        "database": ["db", "postgres", "database", "vector", "indexer"],
    }
    tags: List[str] = []
    for tag, needles in groups.items():
        if any(n in hay for n in needles):
            tags.append(tag)
    return tags or ["generic_ops"]


def check_disk() -> Dict[str, Any]:
    r = safe_cmd(["df", "-P", "/"])
    percent = None
    lines = r.get("output", "").splitlines()
    if len(lines) >= 2:
        parts = lines[1].split()
        if len(parts) >= 5 and parts[4].endswith("%"):
            try:
                percent = int(parts[4].rstrip("%"))
            except ValueError:
                pass
    return {"kind": "disk", "percent": percent, "raw": r}


def check_memory_paths() -> Dict[str, Any]:
    paths = [
        Path("/var/lib/octopus"),
        BASE / "data",
        BASE / "experience",
        BASE / "instructions" / "COMPACT_CONTEXT.md",
    ]
    return {"kind": "memory_paths", "paths": {str(p): p.exists() for p in paths}}


def check_api() -> Dict[str, Any]:
    endpoints = [
        "http://127.0.0.1:8080/health",
        "http://127.0.0.1:8000/health",
        "http://127.0.0.1:9560/health",
        "http://127.0.0.1:9540/health",
    ]
    results = []
    curl = shutil.which("curl")
    for url in endpoints:
        if curl:
            r = safe_cmd([curl, "-sS", "-m", "3", "-o", "/dev/null", "-w", "%{http_code}", url], timeout=5)
            results.append({"url": url, "status": r.get("output", "")[-3:], "rc": r.get("rc")})
    return {"kind": "api", "results": results}


def check_systemd(skill_name: str) -> Dict[str, Any]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {"kind": "systemd", "available": False}
    probes = []
    candidates = {skill_name, skill_name.replace("skill-", "octopus-"), skill_name.replace("_", "-")}
    for c in sorted(candidates):
        unit = c if c.endswith(".service") else f"{c}.service"
        r = safe_cmd([systemctl, "is-active", unit], timeout=4)
        probes.append({"unit": unit, "active": r.get("output"), "rc": r.get("rc")})
    failed = safe_cmd([systemctl, "list-units", "--type=service", "--state=failed", "--no-pager"], timeout=6)
    return {"kind": "systemd", "probes": probes, "failed_sample": failed.get("output", "")[:1000]}


def check_docker() -> Dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return {"kind": "docker", "available": False}
    r = safe_cmd([docker, "ps", "--format", "{{.Names}} {{.Status}}"], timeout=8)
    lines = [x for x in r.get("output", "").splitlines() if x.strip()]
    return {"kind": "docker", "running": len(lines), "sample": lines[:20], "rc": r.get("rc")}


def check_security_ports() -> Dict[str, Any]:
    ss = shutil.which("ss")
    if not ss:
        return {"kind": "ports", "available": False}
    r = safe_cmd([ss, "-tln"], timeout=6)
    ports = []
    for line in r.get("output", "").splitlines()[1:80]:
        ports.append(line)
    return {"kind": "ports", "listening_sample": ports}


def telegram_policy(name: str) -> Dict[str, Any]:
    allowed = name in {"skill-notification", "skill-autonomous-agent"}
    return {
        "kind": "telegram_policy",
        "direct_push_allowed": allowed,
        "policy": "Only autonomous agent notification skill may push to Telegram; all other skills log/report only.",
    }


def build_recommendations(tags: List[str], skill_name: str) -> List[str]:
    recs = [
        "Держать выполнение bounded: один безопасный шаг за запуск.",
        "Перед изменениями записывать rollback/changes_log и проверять consent gates.",
        "Не выводить секреты в stdout/stderr; хранить только ключи/статусы.",
    ]
    if "telegram" in tags and skill_name not in {"skill-notification", "skill-autonomous-agent"}:
        recs.append("Не отправлять Telegram напрямую; использовать только журнал/notification skill через автономного агента.")
    if "aws_cost" in tags:
        recs.append("AWS/облака: только read-only audit без создания платных ресурсов и без включения остановленных нод.")
    if "disk" in tags:
        recs.append("Очистку делать только безопасными allowlist-командами; сначала dry-run и отчёт размера.")
    if "llm_ai" in tags:
        recs.append("ИИ-улучшения сохранять как proposals/references; автоприменять только малые безопасные патчи.")
    return recs


def run(skill_dir: Path, context: str = "") -> Dict[str, Any]:
    skill = read_skill(skill_dir)
    name = skill["name"] or skill_dir.name
    text = skill["text"]
    tags = classify(name, text)
    checks: List[Dict[str, Any]] = []
    if "disk" in tags:
        checks.append(check_disk())
    if "memory" in tags:
        checks.append(check_memory_paths())
    if "api" in tags:
        checks.append(check_api())
    if "systemd" in tags:
        checks.append(check_systemd(skill_dir.name))
    if "docker_swarm" in tags:
        checks.append(check_docker())
    if "security" in tags:
        checks.append(check_security_ports())
    if "telegram" in tags:
        checks.append(telegram_policy(name))
    if not checks:
        checks.extend([check_memory_paths(), check_disk()])
    has_algorithm = bool(re.search(r"##\s*Алгоритм", text))
    has_tests = (skill_dir / "tests").exists() and any((skill_dir / "tests").iterdir())
    report = {
        "ok": True,
        "skill": name,
        "path": str(skill_dir),
        "timestamp": now(),
        "tags": tags,
        "description": skill["description"][:500],
        "contract": {
            "has_skill_md": (skill_dir / "SKILL.md").exists(),
            "has_algorithm": has_algorithm,
            "has_runtime": True,
            "has_tests": has_tests,
            "bounded_read_only_default": True,
        },
        "context_sample": context[:400],
        "checks": checks,
        "recommendations": build_recommendations(tags, name),
    }
    return report


def main(skill_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a converted Octopus skill safely")
    parser.add_argument("--skill-dir", default=str(skill_dir) if skill_dir else None)
    parser.add_argument("--context", default="")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args([] if skill_dir else None)
    sd = Path(args.skill_dir) if args.skill_dir else Path.cwd().parent
    report = run(sd, context=args.context)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
