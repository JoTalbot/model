from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.factory import build_memory_port
from swarm.memory.types import Artifact, MemoryAdapterError


def test_factory_disabled():
    assert build_memory_port({"memory_facade": {"enabled": False}}, None) is None


@pytest.mark.asyncio
async def test_factory_enabled_builds_composite(tmp_path, monkeypatch):
    dm = MagicMock()
    dm._node_id = "node-test"
    dm.store = AsyncMock(return_value="block-1")

    cfg = {
        "memory_facade": {
            "enabled": True,
            "scratch_root": str(tmp_path / "scratch"),
        }
    }
    port = build_memory_port(cfg, dm)
    assert port is not None
    assert isinstance(port, CompositeMemoryPort)

    ref = await port.put(Artifact(content=b"x"))
    assert ref.startswith("ref:file:")


def test_factory_rejects_invalid_outbound_proxy(tmp_path):
    dm = MagicMock()
    dm._node_id = "node-test"
    dm.store = AsyncMock(return_value="block-1")
    cfg = {
        "network": {"outbound_proxy": "ftp://127.0.0.1:1"},
        "memory_facade": {
            "enabled": True,
            "scratch_root": str(tmp_path / "scratch"),
            "cloud_paste": {"nullpointer": True},
        },
    }
    with pytest.raises(MemoryAdapterError, match=r"network\.outbound_proxy"):
        build_memory_port(cfg, dm)


def test_factory_http_links_requires_nonempty_allowlist(tmp_path):
    dm = MagicMock()
    dm._node_id = "node-test"
    dm.store = AsyncMock(return_value="block-1")
    cfg = {
        "memory_facade": {
            "enabled": True,
            "scratch_root": str(tmp_path / "scratch"),
            "http_links": {"enabled": True, "allowlist": []},
        }
    }
    with pytest.raises(MemoryAdapterError, match="allowlist is empty"):
        build_memory_port(cfg, dm)


@pytest.mark.asyncio
async def test_factory_http_links_registers_adapters(tmp_path):
    dm = MagicMock()
    dm._node_id = "node-test"
    dm.store = AsyncMock(return_value="block-1")
    cfg = {
        "memory_facade": {
            "enabled": True,
            "scratch_root": str(tmp_path / "scratch"),
            "http_links": {"enabled": True, "allowlist": ["example.com"]},
        }
    }
    port = build_memory_port(cfg, dm)
    assert port is not None
    assert "https" in port._adapters and "http" in port._adapters


def test_extend_network_adapters_registers_nullpointer(tmp_path):
    from swarm.memory.factory import extend_memory_facade_network_adapters

    adapters: dict[str, object] = {"file": object()}
    cfg = {
        "memory_facade": {
            "scratch_root": str(tmp_path / "scratch"),
            "cloud_paste": {"nullpointer": True},
        },
    }
    extend_memory_facade_network_adapters(cfg, adapters)
    assert "nullpointer" in adapters


def test_extend_passes_pasteee_api_key(tmp_path):
    from swarm.memory.adapters.paste_cloud import PasteEEAdapter
    from swarm.memory.factory import extend_memory_facade_network_adapters

    adapters: dict[str, object] = {"file": object()}
    cfg = {
        "memory_facade": {
            "scratch_root": str(tmp_path / "scratch"),
            "cloud_paste": {"pasteee": True, "pasteee_api_key": "app-key-xyz"},
        },
    }
    extend_memory_facade_network_adapters(cfg, adapters)
    inst = adapters["pasteee"]
    assert isinstance(inst, PasteEEAdapter)
    assert inst._api_key == "app-key-xyz"


def test_extend_pasteee_prefers_yaml_key_over_env(tmp_path, monkeypatch):
    from swarm.memory.adapters.paste_cloud import PasteEEAdapter
    from swarm.memory.factory import extend_memory_facade_network_adapters

    monkeypatch.setenv("PASTE_EE_API_KEY", "from-env")
    adapters: dict[str, object] = {"file": object()}
    cfg = {
        "memory_facade": {
            "scratch_root": str(tmp_path / "scratch"),
            "cloud_paste": {
                "pasteee": True,
                "pasteee_api_key": "from-yaml",
            },
        },
    }
    extend_memory_facade_network_adapters(cfg, adapters)
    assert isinstance(adapters["pasteee"], PasteEEAdapter)
    assert adapters["pasteee"]._api_key == "from-yaml"
