"""Тесты для swarm.plugins — registry, loader, base, health_check."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.plugins.base import Plugin
from swarm.plugins.health_check import _classify
from swarm.plugins.loader import load_plugins
from swarm.plugins.registry import PluginRegistry

# ── Plugin base ───────────────────────────────────────────────────────────


class TestPlugin:
    @pytest.mark.asyncio
    async def test_base_setup(self):
        p = Plugin()
        assert p.name == "base"
        await p.setup(MagicMock())  # не падает


# ── PluginRegistry ────────────────────────────────────────────────────────


class TestPluginRegistry:
    def test_register_plugin(self):
        reg = PluginRegistry()
        p = Plugin()
        p.name = "test-plugin"
        reg.register(p)
        assert "test-plugin" in reg.plugins

    def test_register_adapter(self):
        reg = PluginRegistry()
        factory = MagicMock()
        reg.register_adapter("custom", factory)
        assert reg.memory_adapters["custom"] is factory

    def test_register_command(self):
        reg = PluginRegistry()
        cmd = MagicMock()
        reg.register_command("my-cmd", cmd)
        assert reg.commands["my-cmd"] is cmd

    @pytest.mark.asyncio
    async def test_setup_all(self):
        reg = PluginRegistry()
        p1 = MagicMock(spec=Plugin)
        p1.name = "p1"
        p1.setup = AsyncMock()
        p2 = MagicMock(spec=Plugin)
        p2.name = "p2"
        p2.setup = AsyncMock()

        reg.register(p1)
        reg.register(p2)

        container = MagicMock()
        await reg.setup_all(container)
        p1.setup.assert_called_once_with(container)
        p2.setup.assert_called_once_with(container)


# ── Loader ────────────────────────────────────────────────────────────────


class TestLoader:
    def test_load_health_check_plugin(self):
        reg = PluginRegistry()
        load_plugins(["swarm.plugins.health_check"], reg)
        assert "health_check" in reg.plugins

    def test_load_invalid_module_raises(self):
        reg = PluginRegistry()
        with pytest.raises(Exception):
            load_plugins(["nonexistent.module.xyz"], reg)


# ── HealthCheck classify ──────────────────────────────────────────────────


class TestClassify:
    def test_healthy(self):
        assert _classify(1.0) == "healthy"
        assert _classify(0.95) == "healthy"

    def test_degraded(self):
        assert _classify(0.85) == "degraded"
        assert _classify(0.7) == "degraded"

    def test_down(self):
        assert _classify(0.4) == "down"
        assert _classify(0.0) == "down"

    def test_custom_thresholds(self):
        assert _classify(0.6, degraded=0.7, down=0.3) == "degraded"
        assert _classify(0.2, degraded=0.7, down=0.3) == "down"
        assert _classify(0.8, degraded=0.7, down=0.3) == "healthy"
