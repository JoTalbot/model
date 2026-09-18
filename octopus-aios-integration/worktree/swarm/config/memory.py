from __future__ import annotations

from typing import Any

from swarm.config.base import ConfigModel
from swarm.config.compat import Field, model_validator


class MemoryConfig(ConfigModel):
    replication_factor: int = 3
    shard_count: int = 5
    repair_interval: int = 60

    data_shards: int = 4
    parity_shards: int = 2
    health_check_interval: int = 60
    repair_interval_seconds: int = 0
    repair_rpc_timeout_seconds: float = 8.0
    repair_max_peers_per_shard: int = 32
    repair_parallel_fetches: int = 3
    repair_rpc_port_offset: int = 2000
    repair_seeds: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("shard_count") is None and out.get("data_shards") is not None:
            out["shard_count"] = out["data_shards"]
        if out.get("repair_interval") is None and out.get("repair_interval_seconds") is not None:
            out["repair_interval"] = out["repair_interval_seconds"]
        return out
