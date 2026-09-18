from __future__ import annotations

from typing import Any

from swarm.config.base import ConfigModel
from swarm.config.compat import model_validator


class ChatConfig(ConfigModel):
    max_rounds: int = 10
    summary_interval: int = 3

    selector: str = "round_robin"
    done_keyword: str = "[DONE]"
    max_llm_calls_per_session: int = 30
    selector_max_llm_calls: int = 15
    max_context_chars: int = 12000
    retry_failed_round: bool = False
    summary_every_n_agent_messages: int = 0
    summary_model: str | None = None
    final_summary: bool = False
    lan_hints: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("summary_interval") is None and out.get("summary_every_n_agent_messages") is not None:
            out["summary_interval"] = out["summary_every_n_agent_messages"]
        return out
