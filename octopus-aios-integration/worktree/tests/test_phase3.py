"""Tests for Phase 3: instrumented gossip/repair, POST endpoints,
Telegram commands, health check plugin.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request

from swarm.api.auth import DashboardAuth
from swarm.events.bus import EventBus
from swarm.memory.port import MemoryMetrics

# ---------------------------------------------------------------------------
# GossipProtocol instrumentation
# ---------------------------------------------------------------------------


class TestGossipInstrumentation:
    def test_gossip_accepts_bus(self):
        from swarm.network.gossip import GossipProtocol
        bus = EventBus()
        g = GossipProtocol(host="127.0.0.1", port=0, bus=bus)
        assert g._bus is bus

    def test_gossip_stats(self):
        from swarm.network.gossip import GossipProtocol
        g = GossipProtocol(host="127.0.0.1", port=0)
        s = g.stats()
        assert "total_received" in s
        assert "total_sent" in s
        assert "peers" in s
        assert s["interval"] == 5.0

    def test_gossip_counters_init_zero(self):
        from swarm.network.gossip import GossipProtocol
        g = GossipProtocol(host="127.0.0.1", port=0)
        assert g.total_received == 0
        assert g.total_sent == 0


# ---------------------------------------------------------------------------
# RepairLoop instrumentation
# ---------------------------------------------------------------------------


class TestRepairInstrumentation:
    def test_repair_loop_accepts_bus(self):
        from swarm.agent.repair import RepairLoop

        class FakeMem:
            async def scan_and_repair_round(self):
                return 0

        bus = EventBus()
        rl = RepairLoop(FakeMem(), 60, bus=bus)
        assert rl._bus is bus

    def test_repair_loop_stats(self):
        from swarm.agent.repair import RepairLoop

        class FakeMem:
            async def scan_and_repair_round(self):
                return 0

        rl = RepairLoop(FakeMem(), 60)
        s = rl.stats()
        assert s["rounds_completed"] == 0
        assert s["running"] is False


# ---------------------------------------------------------------------------
# POST endpoints
# ---------------------------------------------------------------------------


class TestPOSTEndpoints:
    def _make_server(self):
        from swarm.api.control_plane import ControlPlaneServer
        metrics = MemoryMetrics()
        return ControlPlaneServer(metrics, host="127.0.0.1", port=0)

    def test_post_task_no_container(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/tasks"
            body = json.dumps({"description": "test task"}).encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 503")
            except urllib.error.HTTPError as e:
                assert e.code == 503
        finally:
            server.stop()

    def test_post_task_missing_description(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/tasks"
            body = json.dumps({}).encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 400")
            except urllib.error.HTTPError as e:
                # 400 bad request or 503 no container
                assert e.code in (400, 503)
        finally:
            server.stop()

    def test_post_memory_insert_no_container(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/memory/insert"
            body = json.dumps({"table": "test", "data": {"x": 1}}).encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 503")
            except urllib.error.HTTPError as e:
                assert e.code == 503
        finally:
            server.stop()

    def test_post_bootstrap_no_container(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/network/bootstrap"
            body = json.dumps({"host": "10.0.0.1", "port": 8000}).encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 503")
            except urllib.error.HTTPError as e:
                assert e.code == 503
        finally:
            server.stop()

    def test_post_config_reload_no_container(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/config/reload"
            req = urllib.request.Request(url, data=b"{}", method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 503")
            except urllib.error.HTTPError as e:
                assert e.code == 503
        finally:
            server.stop()

    def test_post_repair_trigger_no_container(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/memory/repair/trigger"
            req = urllib.request.Request(url, data=b"{}", method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 503")
            except urllib.error.HTTPError as e:
                assert e.code == 503
        finally:
            server.stop()

    def test_post_gossip_inject_no_container(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/gossip/inject"
            body = json.dumps({"msg_type": "TEST", "payload": {}}).encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 503")
            except urllib.error.HTTPError as e:
                assert e.code == 503
        finally:
            server.stop()

    def test_post_invalid_json(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/tasks"
            req = urllib.request.Request(url, data=b"not json{", method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Content-Length", "9")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 400")
            except urllib.error.HTTPError as e:
                assert e.code == 400
        finally:
            server.stop()

    def test_post_unknown_route_404(self):
        server = self._make_server()
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/nonexistent"
            req = urllib.request.Request(url, data=b"{}", method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            server.stop()

    def test_post_auth_required(self):
        from swarm.api.control_plane import ControlPlaneServer
        metrics = MemoryMetrics()
        auth = DashboardAuth({"dashboard": {"token": "secret"}})
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0, auth=auth)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/tasks"
            req = urllib.request.Request(url, data=b'{"description":"x"}', method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("should 401")
            except urllib.error.HTTPError as e:
                assert e.code == 401
        finally:
            server.stop()


# ---------------------------------------------------------------------------
# Telegram bot new commands
# ---------------------------------------------------------------------------


class TestTelegramNewCommands:
    def test_format_status_still_works(self):
        from swarm.memory.telegram import format_status
        metrics = MemoryMetrics()
        metrics.record_put("file")
        result = format_status(metrics.snapshot())
        assert "file" in result

    def test_cmd_health_no_metrics(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        bot = TelegramBot(BotConfig(token="fake", open_access=True))
        bot._metrics = None

        async def _run():
            from swarm.memory.telegram import _cmd_health
            result = await _cmd_health(bot, {}, "")
            assert "No metrics" in result

        asyncio.run(_run())

    def test_cmd_health_with_metrics(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        metrics = MemoryMetrics()
        metrics.record_put("catbox")
        metrics.record_get("catbox", ok=True)
        metrics.record_get("nullpointer", ok=False)
        metrics.record_error("nullpointer", "HTTP 503")

        bot = TelegramBot(BotConfig(token="fake", open_access=True), metrics=metrics)

        async def _run():
            from swarm.memory.telegram import _cmd_health
            result = await _cmd_health(bot, {}, "")
            assert "catbox" in result
            assert "nullpointer" in result

        asyncio.run(_run())

    def test_cmd_alerts_no_errors(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        metrics = MemoryMetrics()
        metrics.record_put("file")
        bot = TelegramBot(BotConfig(token="fake", open_access=True), metrics=metrics)

        async def _run():
            from swarm.memory.telegram import _cmd_alerts
            result = await _cmd_alerts(bot, {}, "")
            assert "No recent errors" in result

        asyncio.run(_run())

    def test_cmd_alerts_with_errors(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        metrics = MemoryMetrics()
        metrics.record_error("catbox", "timeout")
        # Need to register the scheme first
        metrics.record_put("catbox")
        bot = TelegramBot(BotConfig(token="fake", open_access=True), metrics=metrics)

        async def _run():
            from swarm.memory.telegram import _cmd_alerts
            result = await _cmd_alerts(bot, {}, "")
            assert "catbox" in result
            assert "timeout" in result

        asyncio.run(_run())

    def test_cmd_peers_no_container(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        bot = TelegramBot(BotConfig(token="fake", open_access=True))

        async def _run():
            from swarm.memory.telegram import _cmd_peers
            result = await _cmd_peers(bot, {}, "")
            assert "not attached" in result

        asyncio.run(_run())

    def test_cmd_tasks_no_container(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        bot = TelegramBot(BotConfig(token="fake", open_access=True))

        async def _run():
            from swarm.memory.telegram import _cmd_tasks
            result = await _cmd_tasks(bot, {}, "")
            assert "not attached" in result

        asyncio.run(_run())

    def test_cmd_task_create_no_container(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        bot = TelegramBot(BotConfig(token="fake", open_access=True))

        async def _run():
            from swarm.memory.telegram import _cmd_task_create
            result = await _cmd_task_create(bot, {}, "test task")
            assert "not attached" in result

        asyncio.run(_run())

    def test_cmd_task_create_empty(self):
        from swarm.memory.telegram import BotConfig, TelegramBot
        bot = TelegramBot(BotConfig(token="fake", open_access=True))
        bot._container = object()  # fake

        async def _run():
            from swarm.memory.telegram import _cmd_task_create
            result = await _cmd_task_create(bot, {}, "")
            assert "usage" in result

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Health check plugin
# ---------------------------------------------------------------------------


class TestHealthCheckPlugin:
    def test_classify(self):
        from swarm.plugins.health_check import _classify
        assert _classify(1.0) == "healthy"
        assert _classify(0.95) == "healthy"
        assert _classify(0.85) == "degraded"
        assert _classify(0.4) == "down"

    def test_plugin_has_name(self):
        from swarm.plugins.health_check import HealthCheckPlugin
        p = HealthCheckPlugin()
        assert p.name == "health_check"

    def test_get_plugin(self):
        from swarm.plugins.health_check import get_plugin
        p = get_plugin()
        assert p.name == "health_check"


# ---------------------------------------------------------------------------
# Gossip stats in API
# ---------------------------------------------------------------------------


class TestGossipStatsAPI:
    def test_gossip_api_includes_stats(self):
        from swarm.api.control_plane import ControlPlaneServer
        metrics = MemoryMetrics()
        server = ControlPlaneServer(metrics, host="127.0.0.1", port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/api/v1/network/gossip"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                assert "stats" in data
                assert "messages" in data
        finally:
            server.stop()
