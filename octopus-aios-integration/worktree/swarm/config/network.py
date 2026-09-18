from __future__ import annotations

from swarm.config.base import ConfigModel
from swarm.config.compat import Field


class NodeConfig(ConfigModel):
    port: int = 8000
    bootstrap: list[str] | str = Field(default_factory=list)
    advertise_host: str = "127.0.0.1"


class TorConfig(ConfigModel):
    enabled: bool = False
    proxy_url: str = "socks5://127.0.0.1:9050"
    control_port: int = 9051
    hidden_service_port: int = 80
    data_dir: str = ".swarm_tor"


class NetworkConfig(ConfigModel):
    host: str = "0.0.0.0"
    port: int = 8000
    bootstrap_host: str | None = None
    bootstrap_port: int | None = None
    outbound_proxy: str | None = None
    tor: TorConfig = Field(default_factory=TorConfig)
