from __future__ import annotations

import yaml

from swarm.config.app import AppConfig
from swarm.config.compat import ValidationError


def load_config(path: str) -> AppConfig:
    """Load and validate the YAML application config from ``path``."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"invalid config {path}: {exc}") from exc
