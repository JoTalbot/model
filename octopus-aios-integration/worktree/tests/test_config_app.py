"""Тесты для swarm.config.app, config.compat — полная конфигурация и pydantic fallback."""


from swarm.config.app import (
    AgentConfig,
    AppConfig,
    DashboardConfig,
    GossipConfig,
    MDNSConfig,
    MemoryFacadeConfig,
)
from swarm.config.compat import BaseModel, Field, ValidationError

# ── AppConfig ─────────────────────────────────────────────────────────────


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig.model_validate({})
        assert cfg.node.port == 8000
        assert cfg.gossip.interval == 5.0
        assert cfg.dashboard.enabled is False
        assert cfg.agents == []

    def test_full_config_yaml(self):
        """Парсинг конфига, аналогичного config.yaml."""
        raw = {
            "node": {"port": 9000, "bootstrap": ["10.0.0.1:8000"]},
            "llm": {
                "base_url": "https://openrouter.ai/api/v1",
                "keys": ["key1"],
                "models": ["model-a"],
                "timeout": 60,
                "max_retries": 5,
            },
            "gossip": {"interval": 10, "fanout": 5},
            "dashboard": {"enabled": True, "port": 9200, "token": "secret"},
            "agents": [
                {"name": "parser", "model": "llama-3", "role": "парсер", "system_prompt": "Ты парсер."},
            ],
        }
        cfg = AppConfig.model_validate(raw)
        assert cfg.node.port == 9000
        assert cfg.llm.models == ["model-a"]
        assert cfg.gossip.fanout == 5
        assert cfg.dashboard.token == "secret"
        assert len(cfg.agents) == 1
        assert cfg.agents[0].name == "parser"

    def test_from_config_yaml_file(self):
        from swarm.bootstrap.config import load_config
        cfg = load_config("config.yaml")
        assert isinstance(cfg, AppConfig)
        assert len(cfg.agents) >= 1
        assert cfg.node.port == 8000


class TestAgentConfig:
    def test_minimal(self):
        cfg = AgentConfig.model_validate({"name": "a", "model": "m"})
        assert cfg.name == "a"
        assert cfg.role == ""
        assert cfg.system_prompt == ""

    def test_full(self):
        cfg = AgentConfig.model_validate({
            "name": "parser",
            "role": "парсер",
            "model": "llama-3",
            "system_prompt": "Ты парсер цен.",
        })
        assert cfg.role == "парсер"


class TestGossipConfig:
    def test_defaults(self):
        cfg = GossipConfig.model_validate({})
        assert cfg.interval == 5.0
        assert cfg.fanout == 3
        assert cfg.seen_capacity == 1000


class TestMDNSConfig:
    def test_defaults(self):
        cfg = MDNSConfig.model_validate({})
        assert cfg.enabled is False
        assert "_immortal-swarm" in cfg.service_type


class TestDashboardConfig:
    def test_defaults(self):
        cfg = DashboardConfig.model_validate({})
        assert cfg.enabled is False
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9100
        assert cfg.username == "admin"

    def test_with_auth(self):
        cfg = DashboardConfig.model_validate({
            "enabled": True,
            "token": "abc",
            "password": "pass",
        })
        assert cfg.token == "abc"
        assert cfg.password == "pass"


class TestMemoryFacadeConfig:
    def test_defaults(self):
        cfg = MemoryFacadeConfig.model_validate({})
        assert cfg.enabled is False
        assert cfg.scratch_root == ".swarm_scratch"
        assert cfg.default_put_route == "file"


# ── Compat (BaseModel fallback) ──────────────────────────────────────────


class TestCompatBaseModel:
    def test_model_validate_dict(self):
        class MyModel(BaseModel):
            x: int = 0
            y: str = "hello"

        m = MyModel.model_validate({"x": 42, "y": "world"})
        assert m.x == 42
        assert m.y == "world"

    def test_model_validate_defaults(self):
        class MyModel(BaseModel):
            a: int = 10

        m = MyModel.model_validate({})
        assert m.a == 10

    def test_model_dump(self):
        class MyModel(BaseModel):
            x: int = 1

        m = MyModel(x=5)
        d = m.model_dump()
        assert d["x"] == 5

    def test_field_default_factory(self):
        class MyModel(BaseModel):
            items: list = Field(default_factory=list)

        m = MyModel.model_validate({})
        assert m.items == []
        # Разные инстансы не шарят список
        m2 = MyModel.model_validate({})
        m.items.append("x")
        assert m2.items == []

    def test_validation_error_type(self):
        assert issubclass(ValidationError, (ValueError, Exception))

    def test_nested_model(self):
        class Inner(BaseModel):
            v: int = 0

        class Outer(BaseModel):
            inner: Inner = Field(default_factory=Inner)

        m = Outer.model_validate({"inner": {"v": 99}})
        assert m.inner.v == 99

    def test_extra_fields_allowed(self):
        """ConfigModel(extra='allow') разрешает неизвестные поля."""
        from swarm.config.base import ConfigModel

        m = ConfigModel.model_validate({"unknown_key": "value"})
        assert m.get("unknown_key") == "value"
