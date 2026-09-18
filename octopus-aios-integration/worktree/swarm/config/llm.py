from __future__ import annotations

from typing import Any

from swarm.config.base import ConfigModel
from swarm.config.compat import Field, model_validator


class LocalLLMConfig(ConfigModel):
    enabled: bool = False
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)
    prefer_local: bool = False
    api_key: str | None = None
    model_aliases: dict[str, str] = Field(default_factory=dict)


class LLMConfig(ConfigModel):
    """LLM config schema with compatibility for the current OpenRouter YAML."""

    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    timeout: int = 120
    retries: int = 3

    base_url: str | None = None
    keys: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    max_retries: int | None = None
    local: LocalLLMConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("api_base") is None and out.get("base_url") is not None:
            out["api_base"] = out["base_url"]
        if out.get("base_url") is None and out.get("api_base") is not None:
            out["base_url"] = out["api_base"]
        if out.get("api_key") is None and out.get("keys"):
            out["api_key"] = out["keys"][0]
        if out.get("model") is None and out.get("models"):
            out["model"] = out["models"][0]
        if out.get("max_retries") is None and out.get("retries") is not None:
            out["max_retries"] = out["retries"]
        if out.get("retries") is None and out.get("max_retries") is not None:
            out["retries"] = out["max_retries"]
        return out
