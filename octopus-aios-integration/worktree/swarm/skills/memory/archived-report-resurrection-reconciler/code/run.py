#!/usr/bin/env python3
"""Reconcile ITER files resurrected after archive-verified report compaction."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ITER_RE = re.compile(r"^ITER_[0-9]{2,3}\.md$")
DEFAULT_REPORTS = Path("/mnt/agents/-Octopus/reports")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_marker(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def canonical_path(raw: str) -> Path:
    # /root/agents is the legacy source of the canonical /mnt/agents bind mount.
    if raw.startswith("/root/agents/"):
        return Path("/mnt/agents") / raw.removeprefix("/root/agents/")
    return Path(raw)


def strict_iter_files(run_dir: Path) -> list[Path]:
    return [p for p in run_dir.rglob("ITER_*.md") if p.is_file() and ITER_RE.fullmatch(p.name)]


def archive_iter_members(tf: tarfile.TarFile) -> list[tarfile.TarInfo]:
    return [m for m in tf.getmembers() if m.isfile() and ITER_RE.fullmatch(Path(m.name).name)]


def reconcile_run(marker: Path, apply: bool) -> dict[str, Any]:
    run_dir = marker.parent
    meta = parse_marker(marker)
    archive = canonical_path(meta.get("archive", ""))
    expected_hash = meta.get("archive_sha256", "").lower()
    expected_count_raw = meta.get("iter_files_archived", "0")
    result: dict[str, Any] = {
        "run_dir": str(run_dir),
        "marker": str(marker),
        "archive": str(archive),
        "apply": apply,
        "verified": False,
        "removed": 0,
        "bytes_removed": 0,
        "errors": [],
    }
    try:
        expected_count = int(expected_count_raw)
    except ValueError:
        result["errors"].append("invalid iter_files_archived")
        return result
    if not archive.is_file():
        result["errors"].append("archive missing")
        return result
    actual_hash = sha256_file(archive)
    result["archive_sha256"] = actual_hash
    if not expected_hash or actual_hash != expected_hash:
        result["errors"].append("archive sha256 mismatch")
        return result

    current = strict_iter_files(run_dir)
    result["resurrected_count"] = len(current)
    result["resurrected_bytes"] = sum(p.stat().st_size for p in current)
    if not current:
        result["verified"] = True
        result["archive_member_count"] = expected_count
        result["remaining"] = 0
        result["ok"] = True
        return result

    with tarfile.open(archive, "r:gz") as tf:
        members = archive_iter_members(tf)
        result["archive_member_count"] = len(members)
        if len(members) != expected_count:
            result["errors"].append("archive member count mismatch")
            return result
        member_names = {Path(m.name).as_posix() for m in members}
        rel_names = {p.relative_to(run_dir).as_posix() for p in current}
        if not rel_names.issubset(member_names):
            result["errors"].append("resurrected files not fully represented in archive")
            return result
        # Restore-smoke: compare one resurrected file to the archived copy.
        sample = current[0]
        rel = sample.relative_to(run_dir).as_posix()
        extracted = tf.extractfile(tf.getmember(rel))
        if extracted is None:
            result["errors"].append("restore-smoke extraction failed")
            return result
        archived_bytes = extracted.read()
        if hashlib.sha256(archived_bytes).hexdigest() != sha256_file(sample):
            result["errors"].append("restore-smoke sha256 mismatch")
            return result
        result["restore_smoke"] = rel

    result["verified"] = True
    if apply:
        removed = 0
        removed_bytes = 0
        for path in current:
            size = path.stat().st_size
            path.unlink()
            removed += 1
            removed_bytes += size
        result["removed"] = removed
        result["bytes_removed"] = removed_bytes
        result["remaining"] = len(strict_iter_files(run_dir))
        result["ok"] = result["remaining"] == 0
    else:
        result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-runs", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    markers = sorted(args.reports.glob("*/ITER_FILES_ARCHIVED.md"))
    if args.max_runs > 0:
        markers = markers[: args.max_runs]
    rows = [reconcile_run(marker, args.apply) for marker in markers]
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "markers": len(markers),
        "verified_runs": sum(bool(r.get("verified")) for r in rows),
        "resurrected_files": sum(int(r.get("resurrected_count", 0)) for r in rows),
        "resurrected_bytes": sum(int(r.get("resurrected_bytes", 0)) for r in rows),
        "removed_files": sum(int(r.get("removed", 0)) for r in rows),
        "bytes_removed": sum(int(r.get("bytes_removed", 0)) for r in rows),
        "ok": all(bool(r.get("ok")) and not r.get("errors") for r in rows),
        "runs": rows,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text if args.json else f"ok={report['ok']} markers={report['markers']} resurrected={report['resurrected_files']} removed={report['removed_files']} bytes_removed={report['bytes_removed']}", end="" if args.json else "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
