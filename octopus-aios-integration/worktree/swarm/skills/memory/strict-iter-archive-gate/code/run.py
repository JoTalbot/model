#!/usr/bin/env python3
"""Create verified archives and markers for completed unmarked parallel wave runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ITER_RE = re.compile(r"^ITER_[0-9]{2,3}\.md$")
RUN_RE = re.compile(r"^parallel_.+")
DEFAULT_REPORTS = Path("/mnt/agents/-Octopus/reports")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def strict_iter_files(run_dir: Path) -> list[Path]:
    return sorted(
        (p for p in run_dir.rglob("ITER_*.md") if p.is_file() and ITER_RE.fullmatch(p.name)),
        key=lambda p: p.relative_to(run_dir).as_posix(),
    )


def has_completion_evidence(run_dir: Path) -> bool:
    names = {p.name for p in run_dir.iterdir() if p.is_file()}
    return bool(names.intersection({"SUMMARY.md", "SUMMARY_RU.md", "MANIFEST.json", "STATUS.md"}))


def candidates(reports: Path) -> list[Path]:
    rows = []
    for run in reports.iterdir():
        if not run.is_dir() or not RUN_RE.fullmatch(run.name):
            continue
        if (run / "ITER_FILES_ARCHIVED.md").exists() or not has_completion_evidence(run):
            continue
        if strict_iter_files(run):
            rows.append(run)
    return sorted(rows)


def archive_run(run_dir: Path, archive_dir: Path, apply: bool) -> dict[str, Any]:
    files = strict_iter_files(run_dir)
    total_bytes = sum(p.stat().st_size for p in files)
    result: dict[str, Any] = {
        "run_dir": str(run_dir),
        "file_count": len(files),
        "source_bytes": total_bytes,
        "apply": apply,
        "verified": False,
        "marker_written": False,
        "errors": [],
    }
    if not files:
        result["errors"].append("no strict ITER files")
        return result
    if not has_completion_evidence(run_dir):
        result["errors"].append("completion evidence missing")
        return result
    if not apply:
        result["ok"] = True
        return result

    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_archive = archive_dir / f"{run_dir.name}_ITER_files_{stamp}.tar.gz"
    temp_archive = final_archive.with_suffix(final_archive.suffix + ".partial")
    try:
        with tarfile.open(temp_archive, "w:gz") as tf:
            for path in files:
                tf.add(path, arcname=path.relative_to(run_dir).as_posix(), recursive=False)
        digest = sha256_file(temp_archive)
        with tarfile.open(temp_archive, "r:gz") as tf:
            members = [m for m in tf.getmembers() if m.isfile() and ITER_RE.fullmatch(Path(m.name).name)]
            if len(members) != len(files):
                result["errors"].append("archive member count mismatch")
                return result
            names = {Path(m.name).as_posix() for m in members}
            expected = {p.relative_to(run_dir).as_posix() for p in files}
            if names != expected:
                result["errors"].append("archive membership mismatch")
                return result
            sample = files[0]
            rel = sample.relative_to(run_dir).as_posix()
            extracted = tf.extractfile(tf.getmember(rel))
            if extracted is None or hashlib.sha256(extracted.read()).hexdigest() != sha256_file(sample):
                result["errors"].append("restore-smoke mismatch")
                return result
        os.replace(temp_archive, final_archive)
        marker_text = (
            "# ITER files archived\n"
            f"archived_at={datetime.now(timezone.utc).isoformat()}\n"
            f"archive={final_archive}\n"
            f"archive_sha256={digest}\n"
            f"iter_files_archived={len(files)}\n"
            "restore_smoke=success\n"
            "created_by=strict-iter-archive-gate\n"
        )
        marker = run_dir / "ITER_FILES_ARCHIVED.md"
        marker_tmp = run_dir / ".ITER_FILES_ARCHIVED.md.tmp"
        marker_tmp.write_text(marker_text, encoding="utf-8")
        os.replace(marker_tmp, marker)
        result.update({
            "verified": True,
            "marker_written": True,
            "archive": str(final_archive),
            "archive_sha256": digest,
            "archive_bytes": final_archive.stat().st_size,
            "restore_smoke": rel,
            "ok": True,
        })
        return result
    finally:
        if temp_archive.exists():
            temp_archive.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    ap.add_argument("--archive-dir", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-runs", type=int, default=0)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    archive_dir = args.archive_dir or args.reports / "_archives" / "report_compaction_apply"
    runs = candidates(args.reports)
    if args.max_runs > 0:
        runs = runs[: args.max_runs]
    rows = [archive_run(run, archive_dir, args.apply) for run in runs]
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "candidate_runs": len(runs),
        "candidate_files": sum(r["file_count"] for r in rows),
        "candidate_bytes": sum(r["source_bytes"] for r in rows),
        "verified_runs": sum(bool(r.get("verified")) for r in rows),
        "markers_written": sum(bool(r.get("marker_written")) for r in rows),
        "ok": all(bool(r.get("ok")) and not r.get("errors") for r in rows),
        "runs": rows,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text if args.json else f"ok={report['ok']} runs={report['candidate_runs']} files={report['candidate_files']} verified={report['verified_runs']}", end="" if args.json else "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
