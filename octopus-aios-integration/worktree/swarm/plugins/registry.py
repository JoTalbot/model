from __future__ import annotations

from collections.abc import Callable

from swarm.plugins.base import Plugin


class PluginRegistry:
    """Registry for runtime plugins and extension points."""

    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}
        self.memory_adapters: dict[str, Callable] = {}
        self.commands: dict[str, Callable] = {}

    def register(self, plugin: Plugin) -> None:
        self.plugins[plugin.name] = plugin

    def register_adapter(self, scheme: str, factory: Callable) -> None:
        self.memory_adapters[scheme] = factory

    def register_command(self, name: str, command: Callable) -> None:
        self.commands[name] = command

    async def setup_all(self, container) -> None:
        for plugin in self.plugins.values():
            await plugin.setup(container)
