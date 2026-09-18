from __future__ import annotations

import importlib
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml


@dataclass
class Check:
    name: str
    status: str
    detail: str


def _check_python() -> Check:
    version = sys.version_info
    text = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 11):
        return Check("Python", "OK", text)
    return Check("Python", "FAIL", f"{text}; Python >= 3.11 is required")


def _check_imports() -> Check:
    modules = [
        "kademlia",
        "reedsolo",
        "msgpack",
        "httpx",
        "selectolax",
        "yaml",
        "click",
        "colorama",
        "cryptography",
        "qrcode",
        "pydantic",
    ]
    missing: list[str] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    if missing:
        return Check("Dependencies", "FAIL", "missing: " + ", ".join(missing))
    return Check("Dependencies", "OK", f"{len(modules)} modules import")


def _load_config(path: str) -> tuple[dict, Check]:
    p = Path(path)
    if not p.exists():
        return {}, Check("Config", "FAIL", f"{path} not found")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {}, Check("Config", "FAIL", f"could not parse {path}: {exc}")
    if not isinstance(data, dict):
        return {}, Check("Config", "FAIL", f"{path} must contain a YAML mapping")
    return data, Check("Config", "OK", path)


def _check_local_memory(cfg: dict) -> Check:
    root = ((cfg.get("memory_facade") or {}).get("scratch_root") or ".swarm_scratch")
    try:
        p = Path(root).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        return Check("Local memory", "FAIL", f"{root}: {exc}")
    return Check("Local memory", "OK", str(p))


def _tcp_port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _check_ports(cfg: dict) -> Check:
    node = cfg.get("node") or {}
    host = str(node.get("advertise_host") or "127.0.0.1")
    port = int(node.get("port") or 8000)
    rpc_port = port + 2000
    busy: list[str] = []
    for label, candidate in (("node", port), ("rpc", rpc_port)):
        bind_host = "127.0.0.1" if host in {"0.0.0.0", "localhost"} else host
        if not _tcp_port_is_free(bind_host, candidate):
            busy.append(f"{label}:{candidate}")
    if busy:
        return Check("P2P ports", "WARN", "busy: " + ", ".join(busy))
    return Check("P2P ports", "OK", f"node:{port}, rpc:{rpc_port}")


def _check_llm(cfg: dict) -> Check:
    llm = cfg.get("llm") or {}
    keys = [k for k in (llm.get("keys") or []) if str(k).strip()]
    local = llm.get("local") or {}
    local_enabled = bool(local.get("enabled"))
    base_url = str(local.get("base_url") or "").strip()
    models = local.get("models") or []

    if keys:
        return Check("LLM", "OK", f"{len(keys)} cloud key(s) configured")
    if not local_enabled:
        return Check("LLM", "WARN", "no cloud keys and local LLM is disabled")
    if not base_url or not models:
        return Check("LLM", "WARN", "local LLM enabled but base_url/models are incomplete")

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.75)
        try:
            sock.connect((host, port))
        except OSError:
            return Check("LLM", "WARN", f"local endpoint not reachable: {base_url}")
    return Check("LLM", "OK", f"local endpoint reachable: {base_url}")


def run_checks(config_path: str = "config.yaml") -> list[Check]:
    cfg, config_check = _load_config(config_path)
    checks = [_check_python(), _check_imports(), config_check]
    if cfg:
        checks.extend([
            _check_local_memory(cfg),
            _check_ports(cfg),
            _check_llm(cfg),
        ])
    return checks


def format_checks(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks) if checks else 10
    lines = ["Octopus doctor"]
    for check in checks:
        lines.append(f"{check.status:<5} {check.name:<{width}} {check.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = "config.yaml"
    if "--config" in argv:
        idx = argv.index("--config")
        try:
            config_path = argv[idx + 1]
        except IndexError:
            print("doctor: --config requires a path", file=sys.stderr)
            return 2
    elif argv and argv[0] not in {"-h", "--help"}:
        config_path = argv[0]

    if argv and argv[0] in {"-h", "--help"}:
        print("Usage: octopus doctor [--config config.yaml]")
        return 0

    checks = run_checks(config_path)
    print(format_checks(checks))
    return 1 if any(c.status == "FAIL" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
