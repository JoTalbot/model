"""Tests for the control-plane server and supporting modules."""

from __future__ import annotations

import asyncio
import json
import urllib.request

import pytest

from swarm.api.auth import DashboardAuth, RateLimiter
from swarm.api.sse import SSEBridge
from swarm.config.helpers import (
    llm_key_pool,
    llm_local_router_kwargs,
    parse_repair_seeds,
    yaml_bootstrap_addr,
)
from swarm.events.bus import EventBus
from swarm.events.events import (
    AdapterHealthChanged,
    ConfigReloaded,
    GossipReceived,
    GossipSent,
    LLMCallCompleted,
    LLMCallFailed,
    LLMCallStarted,
    MemoryGetFailed,
    MemoryGetOk,
    MemoryPut,
    NodeJoined,
    PeerDiscovered,
    ShardRepairCompleted,
    ShardRepairFailed,
    ShardRepairStarted,
)
from swarm.memory.port import MemoryMetrics

# ---------------------------------------------------------------------------
# DashboardAuth
# ---------------------------------------------------------------------------


class TestDashboardAuth:
    def test_no_auth_configured(self):
        auth = DashboardAuth({})
        assert not auth.enabled
        assert auth.check_header("")

    def test_bearer_token(self):
        auth = DashboardAuth({"dashboard": {"token": "secret123"}})
        assert auth.enabled
        assert auth.check_header("Bearer secret123")
        assert not auth.check_header("Bearer wrong")
        assert not auth.check_header("")

    def test_basic_auth(self):
        auth = DashboardAuth(
            {"dashboard": {"username": "admin", "password": "pw"}}
        )
        assert auth.enabled
        import base64

        good = "Basic " + base64.b64encode(b"admin:pw").decode()
        assert auth.check_header(good)
        bad = "Basic " + base64.b64encode(b"admin:wrong").decode()
        assert not auth.check_header(bad)

    def test_basic_auth_malformed_b64(self):
        auth = DashboardAuth({"dashboard": {"password": "pw"}})
        assert not auth.check_header("Basic !!!not-base64!!!")


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_allows_under_limit(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert rl.allow("1.2.3.4")

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        assert rl.allow("1.2.3.4")
        assert rl.allow("1.2.3.4")
        assert not rl.allow("1.2.3.4")

    def test_different_ips_independent(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        assert rl.allow("1.1.1.1")
        assert not rl.allow("1.1.1.1")
        assert rl.allow("2.2.2.2")


# ---------------------------------------------------------------------------
# SSEBridge
# ---------------------------------------------------------------------------


class TestSSEBridge:
    def test_forward_event(self):
        bus = EventBus()
        bridge = SSEBridge(bus)
        q = bridge.connect()

        async def _run():
            await bus.publish(NodeJoined("abc"))
            data = q.get_nowait()
            assert data["type"] == "NodeJoined"
            assert data["payload"]["node_id"] == "abc"
            assert "ts" in data

        asyncio.run(_run())
        bridge.disconnect(q)
        assert bridge.client_count == 0

    def test_slow_consumer_dropped(self):
        bus = EventBus()
        bridge = SSEBridge(bus, max_queue=1)
        bridge.connect()  # побочный эффект: создаёт consumer

        async def _run():
            await bus.publish(NodeJoined("a"))
            await bus.publish(NodeJoined("b"))

        asyncio.run(_run())
        assert bridge.client_count == 0

    def test_all_event_types_forward(self):
        """All new event types should be subscribed by the bridge."""
        bus = EventBus()
        bridge = SSEBridge(bus)
        q = bridge.connect()

        events = [
            LLMCallStarted(model="gpt-4"),
            LLMCallCompleted(model="gpt-4", tokens_in=10, tokens_out=20, latency_ms=100),
            LLMCallFailed(model="gpt-4", error="timeout", attempt=1),
            MemoryPut(scheme="file", ref="ref:file:abc", size_bytes=100),
            MemoryGetOk(scheme="file", ref="ref:file:abc"),
            MemoryGetFailed(scheme="catbox", ref="ref:catbox:x", error="404"),
            GossipReceived(msg_id="g1", msg_type="TASK_BROADCAST"),
            GossipSent(msg_count=3, target_count=2),
            ShardRepairStarted(block_id="b1"),
            ShardRepairCompleted(block_id="b1", shards_recovered=2),
            ShardRepairFailed(block_id="b2", error="no peers"),
            PeerDiscovered(host="1.2.3.4", port=8000, via="mdns"),
            ConfigReloaded(changed_keys=("gossip.interval",)),
            AdapterHealthChanged(scheme="catbox", status="down", reason="HTTP 503"),
        ]

        async def _run():
            for event in events:
                await bus.publish(event)

        asyncio.run(_run())

        collected = []
        while not q.empty():
            collected.append(q.get_nowait())

        assert len(collected) == len(events)
        types_received = {d["type"] for d in collected}
        types_expected = {type(e).__name__ for e in events}
        assert types_received == types_expected

        bridge.disconnect(q)


# ---------------------------------------------------------------------------
# config/helpers.py
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    def test_yaml_bootstrap_addr_string(self):
        cfg = {"node": {"bootstrap": "192.168.1.1:8000"}}
        assert yaml_bootstrap_addr(cfg) == ("192.168.1.1", 8000)

    def test_yaml_bootstrap_addr_list(self):
        cfg = {"node": {"bootstrap": ["10.0.0.1:9000"]}}
        assert yaml_bootstrap_addr(cfg) == ("10.0.0.1", 9000)

    def test_yaml_bootstrap_addr_empty(self):
        assert yaml_bootstrap_addr({}) is None
        assert yaml_bootstrap_addr({"node": {}}) is None
        assert yaml_bootstrap_addr({"node": {"bootstrap": []}}) is None

    def test_llm_local_router_kwargs_disabled(self):
        assert llm_local_router_kwargs({}) == {}
        assert llm_local_router_kwargs({"local": {"enabled": False}}) == {}

    def test_llm_local_router_kwargs_enabled(self):
        cfg = {
            "local": {
                "enabled": True,
                "base_url": "http://localhost:8080/v1",
                "models": ["llama-3"],
                "prefer_local": True,
                "api_key": "test-key",
            }
        }
        kw = llm_local_router_kwargs(cfg)
        assert kw["local_base_url"] == "http://localhost:8080/v1"
        assert kw["local_models"] == ["llama-3"]
        assert kw["prefer_local"] is True
        assert kw["local_api_key"] == "test-key"

    def test_llm_key_pool_from_keys(self):
        pool = llm_key_pool({"keys": ["k1", "k2"]}, {})
        assert len(pool.keys) == 2

    def test_llm_key_pool_local_fallback(self):
        pool = llm_key_pool({}, {"local_base_url": "http://x"})
        assert len(pool.keys) == 1

    def test_llm_key_pool_raises_without_keys(self):
        with pytest.raises(ValueError, match="Add OpenRouter keys"):
            llm_key_pool({}, {})

    def test_parse_repair_seeds(self):
        assert parse_repair_seeds(["10.0.0.1:8000"]) == [("10.0.0.1", 8000)]
        assert parse_repair_seeds([]) == []
        assert parse_repair_seeds("not_a_list") == []
        assert parse_repair_seeds(["invalid"]) == []
        assert parse_repair_seeds(["host:abc"]) == []


# ---------------------------------------------------------------------------
# New event types
# ---------------------------------------------------------------------------


class TestNewEventTypes:
    def test_gossip_events_fields(self):
        e = GossipReceived(msg_id="x", msg_type="TASK", from_addr="1.2.3.4:8001")
        assert e.msg_id == "x"
        assert e.from_addr == "1.2.3.4:8001"

    def test_llm_events_fields(self):
        e = LLMCallCompleted(model="gpt-4", tokens_in=10, tokens_out=20, latency_ms=150.5)
        assert e.tokens_in == 10
        assert e.latency_ms == 150.5

    def test_memory_events_fields(self):
        e = MemoryPut(scheme="catbox", ref="ref:catbox:abc", size_bytes=1024)
        assert e.scheme == "catbox"

    def test_shard_repair_events(self):
        e = ShardRepairCompleted(block_id="b1", shards_recovered=3)
        assert e.shards_recovered == 3

    def test_peer_discovered(self):
        e = PeerDiscovered(host="10.0.0.1", port=8000, via="mdns")
        assert e.via == "mdns"

    def test_config_reloaded(self):
        e = ConfigReloaded(changed_keys=("gossip.interval", "llm.models"))
        assert "gossip.interval" in e.changed_keys

    def test_adapter_health_changed(self):
        e = AdapterHealthChanged(scheme="catbox", status="down", reason="503")
        assert e.status == "down"

    def test_all_events_are_frozen(self):
        """All event dataclasses should be frozen (immutable)."""
        import dataclasses

        from swarm.events import events as mod

        for name in dir(mod):
            obj = getattr(mod, name)
            if dataclasses.is_dataclass(obj) and isinstance(obj, type):
                assert obj.__dataclass_params__.frozen, f"{name} is not frozen"


# ---------------------------------------------------------------------------
# ControlPlaneServer (integration)
# ---------------------------------------------------------------------------


class TestControlPlaneServer:
    def test_start_stop_healthz(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        metrics.record_put("file")
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/healthz"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert data["ok"] is True
                assert data["scheme_count"] >= 1
        finally:
            server.stop()

    def test_spa_returns_html(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/"
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode()
                assert "Octopus" in body
                assert "nav" in body  # updated: sidebar renamed to nav in new SPA
                # Check for new pages
                assert "page-llm" in body  # updated
                assert "page-events" in body  # updated SPA id
                assert "page-tasks" in body  # updated SPA id (config page removed, tasks page exists)
        finally:
            server.stop()

    def test_spa_all_routes_return_html(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            for page in ["/nodes", "/tasks", "/memory", "/network",
                         "/llm", "/events", "/config"]:
                url = f"http://127.0.0.1:{server.port}{page}"
                with urllib.request.urlopen(url, timeout=5) as resp:
                    body = resp.read().decode()
                    assert "Octopus" in body, f"{page} failed"
        finally:
            server.stop()

    def test_api_memory_metrics(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        metrics.record_put("catbox")
        metrics.record_put("catbox")
        metrics.record_get("catbox", ok=True)
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/memory/metrics"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert "catbox" in data
                assert data["catbox"]["puts"] == 2
        finally:
            server.stop()

    def test_api_node_info_standalone(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/node/info"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert "node_id" in data
                assert "node_id" in data  # updated: standalone returns minimal info
        finally:
            server.stop()

    def test_api_llm_usage_standalone(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/llm/usage"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert "total_calls" in data
                assert "calls_per_model" in data
                assert data["total_calls"] == 0
        finally:
            server.stop()

    def test_api_gossip_standalone(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/network/gossip"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert "messages" in data
                assert "total_seen" in data
        finally:
            server.stop()

    def test_prometheus_metrics(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        metrics.record_put("file")
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode()
                assert "swarm_memory_puts_total" in body
        finally:
            server.stop()

    def test_404_for_unknown_path(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/nonexistent"
            req = urllib.request.Request(url)
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should have raised")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            server.stop()

    def test_auth_blocks_without_token(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        auth = DashboardAuth({"dashboard": {"token": "secret"}})
        server = ControlPlaneServer(
            metrics, host="127.0.0.1", port=0, auth=auth
        )
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/node/info"
            req = urllib.request.Request(url)
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should have raised 401")
            except urllib.error.HTTPError as e:
                assert e.code == 401

            req2 = urllib.request.Request(url)
            req2.add_header("Authorization", "Bearer secret")
            with urllib.request.urlopen(req2, timeout=5) as resp:
                data = json.loads(resp.read())
                assert "node_id" in data
        finally:
            server.stop()

    def test_healthz_bypasses_auth(self):
        """Health endpoint should be accessible without auth."""
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        auth = DashboardAuth({"dashboard": {"token": "secret"}})
        server = ControlPlaneServer(
            metrics, host="127.0.0.1", port=0, auth=auth
        )
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/healthz"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert data["ok"] is True
        finally:
            server.stop()

    def test_manifest_json(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/manifest.json"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert data["short_name"] == "Swarm"
                assert data["display"] == "standalone"
        finally:
            server.stop()

    def test_cors_preflight(self):
        from swarm.api.control_plane import ControlPlaneServer

        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/node/info"
            req = urllib.request.Request(url, method="OPTIONS")
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
                assert "Access-Control-Allow-Origin" in resp.headers
        finally:
            server.stop()
