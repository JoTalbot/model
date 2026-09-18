from __future__ import annotations

from typing import Any

from swarm.config.compat import BaseModel, ConfigDict


class ConfigModel(BaseModel):
    """Pydantic model with temporary dict-style compatibility helpers."""

    model_config = ConfigDict(extra="allow")

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and hasattr(self, key)
