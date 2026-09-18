import pytest

from swarm.bootstrap.config import load_config
from swarm.events import BlockStored, EventBus, TaskCompleted
from swarm.plugins.base import Plugin
from swarm.plugins.registry import PluginRegistry


async def _noop_handler(_event):
    return None


def test_load_config_returns_typed_model_with_dict_compatibility(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
llm:
  base_url: http://example.test/v1
  keys: [test-key]
  models: [test-model]
  timeout: 9
  max_retries: 2
memory:
  data_shards: 3
  parity_shards: 1
chat:
  max_rounds: 4
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_path))

    assert cfg.llm.base_url == "http://example.test/v1"
    assert cfg["llm"]["models"] == ["test-model"]
    assert cfg.memory.data_shards == 3
    assert cfg.get("chat").get("max_rounds") == 4


@pytest.mark.asyncio
async def test_event_bus_publishes_to_async_and_sync_handlers():
    bus = EventBus()
    seen = []

    async def on_completed(event):
        seen.append(("async", event.task_id, event.result_ref))

    def on_completed_sync(event):
        seen.append(("sync", event.task_id, event.result_ref))

    bus.subscribe(TaskCompleted, on_completed)
    bus.subscribe(TaskCompleted, on_completed_sync)
    bus.subscribe(BlockStored, _noop_handler)

    await bus.publish(TaskCompleted("task-1", "ref:swarm:block-1"))

    assert seen == [
        ("async", "task-1", "ref:swarm:block-1"),
        ("sync", "task-1", "ref:swarm:block-1"),
    ]


@pytest.mark.asyncio
async def test_plugin_registry_sets_up_plugins_and_adapters():
    class DemoPlugin(Plugin):
        name = "demo"

        async def setup(self, container):
            container["calls"].append(self.name)

    registry = PluginRegistry()
    registry.register(DemoPlugin())
    registry.register_adapter("demo", object)

    container = {"calls": []}
    await registry.setup_all(container)

    assert container["calls"] == ["demo"]
    assert registry.memory_adapters["demo"] is object
