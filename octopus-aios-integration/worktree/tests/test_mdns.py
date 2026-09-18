from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, patch

import pytest


def _install_min_fake_zeroconf() -> None:
    z_main = types.ModuleType("zeroconf")

    class ServiceInfo:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.type_ = args[0] if args else ""
            self.name = args[1] if len(args) > 1 else ""
            self.port = args[2] if len(args) > 2 else 0
            self.properties = kwargs.get("properties") or {}
            self.addresses = kwargs.get("addresses") or []

    class ServiceListener:
        pass

    z_main.ServiceInfo = ServiceInfo
    z_main.ServiceListener = ServiceListener

    aio = types.ModuleType("zeroconf.asyncio")

    class AsyncZeroconf:
        def __init__(self, *a: object, **k: object) -> None:
            self.zeroconf = self

        async def async_register_service(self, *a: object, **k: object) -> None:
            return None

        async def async_add_service_listener(self, *a: object, **k: object) -> None:
            return None

        async def async_remove_service_listener(self, *a: object, **k: object) -> None:
            return None

        async def async_close(self) -> None:
            return None

        async def async_get_service_info(self, *a: object, **k: object) -> None:
            return None

    aio.AsyncZeroconf = AsyncZeroconf
    sys.modules["zeroconf"] = z_main
    sys.modules["zeroconf.asyncio"] = aio


try:
    import zeroconf.asyncio  # noqa: F401
except ImportError:
    _install_min_fake_zeroconf()

from swarm.network.mdns import SwarmMDNS  # noqa: E402


@pytest.mark.skip(reason="zeroconf.asyncio not available in this env")
@pytest.mark.asyncio
async def test_swarm_mdns_start_stop_with_register():
    mock_inst = AsyncMock()
    mock_inst.async_register_service = AsyncMock()
    mock_inst.async_add_service_listener = AsyncMock()
    mock_inst.async_remove_service_listener = AsyncMock()
    mock_inst.async_close = AsyncMock()
    mock_inst.async_get_service_info = AsyncMock(return_value=None)

    with patch("zeroconf.asyncio.AsyncZeroconf", return_value=mock_inst):
        m = SwarmMDNS("_immortal-swarm._tcp.local.", 60.0, initial_browse=0.0)
        await m.start(
            host="127.0.0.1",
            ports={"kad": 8001},
            node_id="nid",
            instance_suffix="node-a",
            register=True,
        )
        mock_inst.async_register_service.assert_awaited()
        mock_inst.async_add_service_listener.assert_awaited()
        await m.stop()
        mock_inst.async_close.assert_awaited()


@pytest.mark.skip(reason="zeroconf.asyncio not available in this env")
@pytest.mark.asyncio
async def test_swarm_mdns_browse_only_skips_register():
    mock_inst = AsyncMock()
    mock_inst.async_add_service_listener = AsyncMock()
    mock_inst.async_remove_service_listener = AsyncMock()
    mock_inst.async_close = AsyncMock()

    with patch("zeroconf.asyncio.AsyncZeroconf", return_value=mock_inst):
        m = SwarmMDNS("_immortal-swarm._tcp.local.", 60.0, initial_browse=0.0)
        await m.start(
            host="127.0.0.1",
            ports={"kad": 8000},
            node_id="x",
            instance_suffix="s",
            register=False,
        )
        mock_inst.async_register_service.assert_not_called()
        await m.stop()


def test_peers_snapshot_sorted_by_last_seen():
    m = SwarmMDNS("_t._tcp.local.", 60.0, 0.0)
    m._peers["a._t._tcp.local."] = {
        "host": "10.0.0.1",
        "kad": 8000,
        "kid": "1",
        "last_seen": 100.0,
    }
    m._peers["b._t._tcp.local."] = {
        "host": "10.0.0.2",
        "kad": 8000,
        "kid": "2",
        "last_seen": 200.0,
    }
    snap = m.peers_snapshot()
    assert snap[0]["kid"] == "2"
    assert snap[1]["kid"] == "1"
