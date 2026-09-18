from __future__ import annotations

from swarm.config.base import ConfigModel
from swarm.config.chat import ChatConfig
from swarm.config.compat import Field
from swarm.config.llm import LLMConfig
from swarm.config.memory import MemoryConfig
from swarm.config.network import NetworkConfig, NodeConfig


class AgentConfig(ConfigModel):
    name: str
    role: str = ""
    model: str
    system_prompt: str = ""


class MDNSConfig(ConfigModel):
    enabled: bool = False
    service_type: str = "_immortal-swarm._tcp.local."
    initial_browse_seconds: float = 5.0
    refresh_interval_seconds: float = 60.0


class GossipConfig(ConfigModel):
    interval: float = 5.0
    fanout: int = 3
    seen_capacity: int = 1000


class MemoryFacadeConfig(ConfigModel):
    enabled: bool = False
    scratch_root: str = ".swarm_scratch"
    default_put_route: str = "file"


class DashboardConfig(ConfigModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 9100
    token: str | None = None
    username: str = "admin"
    password: str | None = None


class AppConfig(ConfigModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    node: NodeConfig = Field(default_factory=NodeConfig)
    mdns: MDNSConfig = Field(default_factory=MDNSConfig)
    gossip: GossipConfig = Field(default_factory=GossipConfig)
    memory_facade: MemoryFacadeConfig = Field(default_factory=MemoryFacadeConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    agents: list[AgentConfig] = Field(default_factory=list)
