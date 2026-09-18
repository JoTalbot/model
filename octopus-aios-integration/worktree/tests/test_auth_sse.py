"""Тесты для swarm.api.auth и swarm.api.sse."""

import base64

import pytest

from swarm.api.auth import DashboardAuth, RateLimiter
from swarm.api.sse import SSEBridge, _event_to_dict
from swarm.events.bus import EventBus
from swarm.events.events import NodeJoined, TaskCompleted

# ── DashboardAuth ─────────────────────────────────────────────────────────


class TestDashboardAuth:
    def test_no_auth_configured(self):
        auth = DashboardAuth({})
        assert auth.enabled is False
        assert auth.check_header("") is True
        assert auth.check_header("anything") is True

    def test_bearer_token(self):
        auth = DashboardAuth({"dashboard": {"token": "secret123"}})
        assert auth.enabled is True
        assert auth.check_header("Bearer secret123") is True
        assert auth.check_header("Bearer wrong") is False
        assert auth.check_header("") is False

    def test_basic_auth(self):
        auth = DashboardAuth({"dashboard": {"username": "admin", "password": "pass"}})
        assert auth.enabled is True
        encoded = base64.b64encode(b"admin:pass").decode()
        assert auth.check_header(f"Basic {encoded}") is True

        bad = base64.b64encode(b"admin:wrong").decode()
        assert auth.check_header(f"Basic {bad}") is False

    def test_basic_wrong_user(self):
        auth = DashboardAuth({"dashboard": {"username": "admin", "password": "p"}})
        encoded = base64.b64encode(b"hacker:p").decode()
        assert auth.check_header(f"Basic {encoded}") is False

    def test_bearer_no_token_configured(self):
        """Bearer header без настроенного токена — не пропускаем."""
        auth = DashboardAuth({"dashboard": {"password": "p"}})
        assert auth.check_header("Bearer anything") is False


# ── RateLimiter ───────────────────────────────────────────────────────────


class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert rl.allow("1.2.3.4") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        assert rl.allow("1.1.1.1") is True
        assert rl.allow("1.1.1.1") is True
        assert rl.allow("1.1.1.1") is True
        assert rl.allow("1.1.1.1") is False

    def test_different_ips_independent(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        assert rl.allow("10.0.0.1") is True
        assert rl.allow("10.0.0.2") is True
        assert rl.allow("10.0.0.1") is False


# ── SSEBridge ─────────────────────────────────────────────────────────────


class TestSSEBridge:
    @pytest.mark.asyncio
    async def test_connect_and_receive(self):
        bus = EventBus()
        bridge = SSEBridge(bus)
        q = bridge.connect()
        assert bridge.client_count == 1

        await bus.publish(NodeJoined(node_id="abc"))
        data = q.get_nowait()
        assert data["type"] == "NodeJoined"
        assert data["payload"]["node_id"] == "abc"

    @pytest.mark.asyncio
    async def test_disconnect(self):
        bus = EventBus()
        bridge = SSEBridge(bus)
        q = bridge.connect()
        assert bridge.client_count == 1
        bridge.disconnect(q)
        assert bridge.client_count == 0

    @pytest.mark.asyncio
    async def test_multiple_clients(self):
        bus = EventBus()
        bridge = SSEBridge(bus)
        q1 = bridge.connect()
        q2 = bridge.connect()
        assert bridge.client_count == 2

        await bus.publish(TaskCompleted(task_id="t", result_ref="r"))
        assert not q1.empty()
        assert not q2.empty()

    @pytest.mark.asyncio
    async def test_slow_consumer_dropped(self):
        bus = EventBus()
        bridge = SSEBridge(bus, max_queue=1)
        bridge.connect()  # создаёт consumer

        # Заполняем очередь
        await bus.publish(NodeJoined(node_id="a"))
        await bus.publish(NodeJoined(node_id="b"))
        # Второе сообщение должно выкинуть медленного consumer

    def test_event_to_dict(self):
        d = _event_to_dict(NodeJoined(node_id="n1"))
        assert d["node_id"] == "n1"
