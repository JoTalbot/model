"""Тесты для swarm.config.helpers, base, network, chat.cli_display."""


import pytest

from swarm.chat.cli_display import AGENT_COLORS, AGENT_ICONS, ChatDisplay
from swarm.chat.room import ChatMessage, ChatResult
from swarm.config.base import ConfigModel
from swarm.config.helpers import (
    llm_key_pool,
    llm_local_router_kwargs,
    parse_repair_seeds,
    yaml_bootstrap_addr,
)
from swarm.config.network import NetworkConfig, NodeConfig

# ── ConfigModel ───────────────────────────────────────────────────────────


class TestConfigModel:
    def test_getitem(self):
        m = ConfigModel.model_validate({"x": 1, "y": "hello"})
        assert m["x"] == 1
        assert m["y"] == "hello"

    def test_getitem_missing_raises(self):
        m = ConfigModel.model_validate({})
        with pytest.raises(KeyError):
            _ = m["nonexistent"]

    def test_get_default(self):
        m = ConfigModel.model_validate({})
        assert m.get("missing", 42) == 42

    def test_contains(self):
        m = ConfigModel.model_validate({"x": 1})
        assert "x" in m
        assert "y" not in m


# ── yaml_bootstrap_addr ──────────────────────────────────────────────────


class TestYamlBootstrapAddr:
    def test_valid(self):
        result = yaml_bootstrap_addr({"node": {"bootstrap": ["10.0.0.1:8000"]}})
        assert result == ("10.0.0.1", 8000)

    def test_string_format(self):
        result = yaml_bootstrap_addr({"node": {"bootstrap": "192.168.1.1:9000"}})
        assert result == ("192.168.1.1", 9000)

    def test_empty(self):
        assert yaml_bootstrap_addr({}) is None
        assert yaml_bootstrap_addr({"node": {}}) is None
        assert yaml_bootstrap_addr({"node": {"bootstrap": []}}) is None

    def test_no_colon(self):
        assert yaml_bootstrap_addr({"node": {"bootstrap": ["localhost"]}}) is None


# ── llm_local_router_kwargs ──────────────────────────────────────────────


class TestLlmLocalRouterKwargs:
    def test_disabled(self):
        assert llm_local_router_kwargs({"local": {"enabled": False}}) == {}
        assert llm_local_router_kwargs({}) == {}

    def test_enabled(self):
        result = llm_local_router_kwargs({
            "local": {
                "enabled": True,
                "base_url": "http://127.0.0.1:8080/v1",
                "models": ["llama"],
                "prefer_local": True,
            }
        })
        assert result["local_base_url"] == "http://127.0.0.1:8080/v1"
        assert result["local_models"] == ["llama"]
        assert result["prefer_local"] is True

    def test_with_api_key(self):
        result = llm_local_router_kwargs({
            "local": {
                "enabled": True,
                "base_url": "http://x/v1",
                "models": ["m"],
                "api_key": "secret",
            }
        })
        assert result["local_api_key"] == "secret"

    def test_empty_base_url(self):
        """Пустой base_url → пустой результат."""
        assert llm_local_router_kwargs({
            "local": {"enabled": True, "base_url": "", "models": ["m"]}
        }) == {}


# ── llm_key_pool ─────────────────────────────────────────────────────────


class TestLlmKeyPool:
    def test_with_keys(self):
        pool = llm_key_pool({"keys": ["k1", "k2"]}, {})
        key = pool.get_key()
        assert key.key in ("k1", "k2")

    def test_with_local_only(self):
        pool = llm_key_pool({"keys": []}, {"local_base_url": "http://x"})
        key = pool.get_key()
        assert key.key == "local-placeholder"

    def test_no_keys_no_local_raises(self):
        with pytest.raises(ValueError, match="Add OpenRouter keys"):
            llm_key_pool({"keys": []}, {})


# ── parse_repair_seeds ───────────────────────────────────────────────────


class TestParseRepairSeeds:
    def test_valid(self):
        result = parse_repair_seeds(["10.0.0.1:8000", "10.0.0.2:9000"])
        assert result == [("10.0.0.1", 8000), ("10.0.0.2", 9000)]

    def test_empty(self):
        assert parse_repair_seeds([]) == []
        assert parse_repair_seeds(None) == []
        assert parse_repair_seeds("not a list") == []

    def test_invalid_entries(self):
        result = parse_repair_seeds(["no-port", "host:notanumber", "ok:1234"])
        assert result == [("ok", 1234)]


# ── NetworkConfig / NodeConfig ───────────────────────────────────────────


class TestNetworkConfig:
    def test_defaults(self):
        cfg = NetworkConfig.model_validate({})
        assert cfg.port == 8000
        assert cfg.outbound_proxy is None

    def test_with_proxy(self):
        cfg = NetworkConfig.model_validate({"outbound_proxy": "socks5://127.0.0.1:9050"})
        assert cfg.outbound_proxy == "socks5://127.0.0.1:9050"


class TestNodeConfig:
    def test_defaults(self):
        cfg = NodeConfig.model_validate({})
        assert cfg.port == 8000
        assert cfg.advertise_host == "127.0.0.1"

    def test_custom(self):
        cfg = NodeConfig.model_validate({"port": 9000, "bootstrap": ["10.0.0.1:8000"]})
        assert cfg.port == 9000
        assert cfg.bootstrap == ["10.0.0.1:8000"]


# ── ChatDisplay ──────────────────────────────────────────────────────────


class TestChatDisplay:
    def test_show_goal(self, capsys):
        display = ChatDisplay()
        display.show_goal("Найди цены на стекло")
        captured = capsys.readouterr()
        assert "Найди цены на стекло" in captured.out

    def test_show_message(self, capsys):
        display = ChatDisplay()
        msg = ChatMessage(agent_name="parser", role="parser", content="Нашёл 3 товара", round_num=1)
        display.show_message(msg)
        captured = capsys.readouterr()
        assert "Parser" in captured.out or "parser" in captured.out.lower()
        assert "Нашёл 3 товара" in captured.out

    def test_show_result(self, capsys):
        display = ChatDisplay()
        result = ChatResult(
            messages=[],
            rounds_used=5,
            finished_naturally=True,
            summary="итог",
        )
        display.show_result(result)
        captured = capsys.readouterr()
        assert "5 rounds" in captured.out or "5" in captured.out

    def test_agent_colors_defined(self):
        assert "parser" in AGENT_COLORS
        assert "analyst" in AGENT_COLORS

    def test_agent_icons_defined(self):
        assert "parser" in AGENT_ICONS
