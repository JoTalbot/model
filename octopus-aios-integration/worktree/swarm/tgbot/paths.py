"""Canonical runtime paths for the Telegram resilience subsystem.

Production sets these paths to FHS locations outside the Git checkout. Tests and
portable development retain repository-local defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def state_dir() -> Path:
    return Path(os.environ.get("AIOS_TELEGRAM_STATE_DIR", "") or ROOT / "data")


def log_dir() -> Path:
    return Path(os.environ.get("AIOS_TELEGRAM_LOG_DIR", "") or ROOT / "logs")


def backup_dir() -> Path:
    return Path(
        os.environ.get("AIOS_TELEGRAM_BACKUP_DIR", "")
        or ROOT / "backups" / "telegram-queues"
    )


def state_path(name: str) -> Path:
    return state_dir() / name


def credential_path(name: str, fallback: Path) -> Path:
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    return Path(directory) / name if directory else fallback
