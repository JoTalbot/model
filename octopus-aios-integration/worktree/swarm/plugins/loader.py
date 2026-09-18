from __future__ import annotations

import importlib

from swarm.plugins.base import Plugin
from swarm.plugins.registry import PluginRegistry


def load_plugins(module_names: list[str], registry: PluginRegistry) -> None:
    """Load plugins from import paths.

    A module may expose either ``plugin`` (an instance) or ``get_plugin()``.
    """
    for module_name in module_names:
        module = importlib.import_module(module_name)
        plugin = getattr(module, "plugin", None)
        if plugin is None and hasattr(module, "get_plugin"):
            plugin = module.get_plugin()
        if not isinstance(plugin, Plugin):
            raise TypeError(f"{module_name} does not expose a Plugin instance")
        registry.register(plugin)
