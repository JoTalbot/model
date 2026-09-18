"""Read short-lived secrets from systemd's per-service credential directory."""

from __future__ import annotations

import os
from pathlib import Path


def read_systemd_credential(name: str) -> str:
    """Return a mounted or root-only source credential without logging it.

    Long-running units receive the per-service systemd directory. Root cron
    jobs that have not yet moved to units may read the same protected source
    directory, but only after strict owner/mode checks.
    """
    if not name or "/" in name:
        return ""
    candidates: list[Path] = []
    mounted = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if mounted:
        candidates.append(Path(mounted) / name)
    source = (
        Path(
            os.environ.get(
                "OCTOPUS_CREDENTIAL_SOURCE_DIR",
                os.environ.get(
                    "AIOS_CREDENTIAL_SOURCE_DIR", "/etc/octopus/credentials"
                ),
            )
        )
        / name
    )
    if source not in candidates:
        candidates.append(source)
    for path in candidates:
        try:
            stat = path.stat()
            parent = path.parent.stat()
            # Source credentials must be root-owned and inaccessible to group/
            # other. Mounted systemd credentials may be owned by the service.
            expected_uid = os.geteuid()
            if path == source and (
                stat.st_uid != expected_uid
                or parent.st_uid != expected_uid
                or stat.st_mode & 0o077
                or parent.st_mode & 0o077
            ):
                continue
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return ""


def secret_from_env_or_credential(*env_names: str, credential: str) -> str:
    # A mounted systemd credential deliberately overrides legacy EnvironmentFile
    # values so secret rotation does not depend on editing the process env file.
    mounted = read_systemd_credential(credential)
    if mounted:
        return mounted
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return ""


def import_runtime_credential(env_name: str, credential: str) -> str:
    """Populate an environment variable for legacy callers inside this process."""
    value = read_systemd_credential(credential) or os.environ.get(env_name, "").strip()
    if value:
        os.environ[env_name] = value
    return value
