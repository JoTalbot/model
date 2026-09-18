#!/usr/bin/env python3
"""
Swarm smoke / self-check (offline-first, optional live probes).

Runs the full pytest suite, validates YAML, and optionally tries tiny
``put`` probes against enabled cloud_paste backends (best-effort; failures
inform ops rather than blocking local development).

Environment:
  SWARM_SKIP_NETWORK=1   Never run HTTP probes (default if unset is to probe
                         only when --network is passed).
  SWARM_SMOKE_NETWORK=1  Same as passing --network (legacy alias).

Exit codes: 0 ok, 1 failure.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _repo_root() -> Path:
    return _ROOT


def run_pytest(quiet: bool) -> int:
    root = _repo_root()
    cmd = [sys.executable, "-m", "pytest", root / "tests"]
    if quiet:
        cmd.append("-q")
    else:
        cmd.append("-v")
    print("[smoke] running:", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.call(cmd, cwd=str(root))


def load_cfg(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


async def probe_cloud(cfg: dict, timeout: float) -> dict[str, object]:
    from node import _build_local_memory_port
    from swarm.memory.cloud_fallback import cloud_auto_fallback_schemes
    from swarm.memory.types import Artifact

    port = _build_local_memory_port(cfg)
    schemes = [s for s in cloud_auto_fallback_schemes(cfg) if s != "file"]
    results: dict[str, object] = {}
    for sch in schemes:
        art = Artifact(
            content=b'{"__smoke__":true}',
            mime="application/json",
            tags=["smoke"],
            attrs={"store": sch},
        )
        try:
            ref = await asyncio.wait_for(port.put(art), timeout=timeout)
            results[sch] = {"ok": True, "ref": ref}
        except Exception as exc:
            results[sch] = {"ok": False, "error": str(exc)[:500]}
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    ap.add_argument(
        "--network",
        action="store_true",
        help="Run live HTTP probes against enabled cloud_paste backends",
    )
    ap.add_argument("--probe-timeout", type=float, default=12.0, help="Per-backend timeout")
    ap.add_argument("--skip-pytest", action="store_true", help="Only config / probes")
    ap.add_argument("--json", action="store_true", help="Machine-readable summary on stdout")
    ap.add_argument("-q", "--quiet", action="store_true", help="Quiet pytest")
    args = ap.parse_args()

    root = _repo_root()
    cfg_path = (root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)

    summary: dict[str, object] = {"config": str(cfg_path), "pytest": None, "probes": None}

    if not cfg_path.is_file():
        print(f"[smoke] missing config: {cfg_path}", file=sys.stderr, flush=True)
        return 1

    try:
        cfg = load_cfg(cfg_path)
    except Exception as exc:
        print(f"[smoke] invalid yaml: {exc}", file=sys.stderr, flush=True)
        return 1

    summary["config_ok"] = True

    if not args.skip_pytest:
        rc = run_pytest(args.quiet)
        summary["pytest"] = {"exit_code": rc}
        if rc != 0:
            if args.json:
                print(json.dumps(summary, indent=2))
            return 1

    want_net = args.network or os.environ.get("SWARM_SMOKE_NETWORK", "").strip() in (
        "1",
        "true",
        "yes",
    )
    skip_net = os.environ.get("SWARM_SKIP_NETWORK", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if want_net and not skip_net:
        print("[smoke] live cloud probes (best-effort)…", flush=True)
        summary["probes"] = asyncio.run(probe_cloud(cfg, args.probe_timeout))
    else:
        summary["probes"] = "skipped"

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("[smoke] ok", flush=True)
        if isinstance(summary.get("probes"), dict):
            for sch, row in summary["probes"].items():
                ok = row.get("ok") if isinstance(row, dict) else False
                print(f"  {sch}: {'ok' if ok else 'FAIL'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
