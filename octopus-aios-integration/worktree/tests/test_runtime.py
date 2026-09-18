"""Тесты для swarm.runtime — AppContainer (unit level, без сети)."""

from unittest.mock import MagicMock

from swarm.runtime import AppContainer


class TestAppContainer:
    def test_dataclass_creation(self):
        """AppContainer — dataclass, можно создать с моками."""
        container = AppContainer(
            cfg=MagicMock(),
            bus=MagicMock(),
            plugin_registry=MagicMock(),
            port=8000,
            bootstrap=None,
            kad=MagicMock(),
            gossip=MagicMock(),
            rpc_client=MagicMock(),
            rpc_server=MagicMock(),
            llm=MagicMock(),
            memory=MagicMock(),
            agent=MagicMock(),
            vfs=MagicMock(),
            sync_engine=MagicMock(),
            immortal_manager=MagicMock(),
            linker=MagicMock(),
            archivist=MagicMock(),
            graph_rag=MagicMock(),
        )
        assert container.port == 8000
        assert container.bootstrap is None
        assert container.mdns_inst is None  # default

    def test_container_fields(self):
        """Все ожидаемые поля присутствуют."""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(AppContainer)}
        expected = {
            "cfg", "bus", "plugin_registry", "port", "bootstrap",
            "kad", "gossip", "rpc_client", "rpc_server", "llm",
            "memory", "agent", "vfs", "sync_engine",
            "immortal_manager", "linker", "archivist", "graph_rag",
            "mdns_inst",
        }
        assert expected.issubset(fields)
