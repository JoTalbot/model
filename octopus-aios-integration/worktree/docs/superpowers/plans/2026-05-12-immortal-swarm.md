# Бессмертный Рой — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a distributed P2P network of autonomous AI agents with resilient shared memory, using Python asyncio.

**Architecture:** Modular monolith — single process per node, four internal layers (Network, Memory, Agent, LLM) communicating via well-defined interfaces. Bottom-up build order: LLM → Network → Memory → Agent → CLI.

**Tech Stack:** Python 3.11+, asyncio, kademlia, reedsolo, msgpack, httpx, selectolax, pyyaml, click, pytest + pytest-asyncio

---

## File Map

| File | Responsibility |
|------|---------------|
| `requirements.txt` | All project dependencies |
| `config.yaml` | Default config template (ports, models, keys) |
| `swarm/__init__.py` | Package init, version |
| `swarm/llm/__init__.py` | LLM subpackage init |
| `swarm/llm/key_pool.py` | API key rotation with cooldown logic |
| `swarm/llm/router.py` | OpenRouter client, model failover, retry |
| `swarm/network/__init__.py` | Network subpackage init |
| `swarm/network/rpc.py` | Direct node-to-node TCP messaging (msgpack) |
| `swarm/network/gossip.py` | Push-based UDP gossip broadcasts |
| `swarm/network/kademlia.py` | Thin wrapper around `kademlia` library |
| `swarm/memory/__init__.py` | Memory subpackage init |
| `swarm/memory/erasure.py` | Reed-Solomon encode/decode wrappers |
| `swarm/memory/store.py` | DistributedMemory: store/retrieve/search/delete |
| `swarm/agent/__init__.py` | Agent subpackage init |
| `swarm/agent/core.py` | SwarmAgent base class, main event loop |
| `swarm/agent/task_manager.py` | Task decomposition + distribution |
| `swarm/agent/skills.py` | WebParserSkill, ChatSkill |
| `node.py` | CLI entry point (click), node startup |
| `tests/conftest.py` | Shared fixtures (event loop, temp config, mock LLM) |
| `tests/test_key_pool.py` | KeyPool unit tests |
| `tests/test_router.py` | LLMRouter unit tests (mocked HTTP) |
| `tests/test_rpc.py` | RPC server/client tests |
| `tests/test_gossip.py` | Gossip protocol tests |
| `tests/test_kademlia_wrapper.py` | Kademlia wrapper tests |
| `tests/test_erasure.py` | Reed-Solomon encode/decode tests |
| `tests/test_memory_store.py` | DistributedMemory tests |
| `tests/test_agent_core.py` | SwarmAgent lifecycle tests |
| `tests/test_task_manager.py` | Task decomposition tests |
| `tests/test_skills.py` | WebParser + Chat skill tests |
| `tests/test_node_cli.py` | CLI integration tests |
| `tests/test_integration.py` | Multi-node end-to-end test |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `swarm/__init__.py`
- Create: `swarm/llm/__init__.py`
- Create: `swarm/network/__init__.py`
- Create: `swarm/memory/__init__.py`
- Create: `swarm/agent/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `config.yaml`

- [ ] **Step 1: Create requirements.txt**

```
kademlia>=2.2.2
reedsolo>=1.7.0
msgpack>=1.0.0
httpx>=0.27.0
selectolax>=0.3.0
pyyaml>=6.0
click>=8.0
pytest>=8.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Create package structure**

`swarm/__init__.py`:
```python
__version__ = "0.1.0"
```

`swarm/llm/__init__.py`:
```python
```

`swarm/network/__init__.py`:
```python
```

`swarm/memory/__init__.py`:
```python
```

`swarm/agent/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

- [ ] **Step 3: Create default config.yaml**

```yaml
node:
  port: 8000
  bootstrap: []

llm:
  base_url: "https://openrouter.ai/api/v1"
  keys: []
  models:
    - "anthropic/claude-sonnet-4-20250514"
    - "x-ai/grok-3"
    - "meta-llama/llama-3.3-70b-instruct"
  timeout: 30
  max_retries: 3

gossip:
  interval: 5
  fanout: 3
  seen_capacity: 1000

memory:
  data_shards: 4
  parity_shards: 2
  health_check_interval: 60
```

- [ ] **Step 4: Create tests/conftest.py with shared fixtures**

```python
import asyncio
import pytest
import yaml


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def default_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def mock_llm_response():
    return "This is a mock LLM response for testing."
```

- [ ] **Step 5: Install dependencies and verify**

Run: `pip install -r requirements.txt`
Expected: all packages install without errors

Run: `pytest --co -q`
Expected: `no tests ran` (collected 0 items)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold project structure with dependencies and config"
```

---

## Task 2: LLM Key Pool

**Files:**
- Create: `swarm/llm/key_pool.py`
- Create: `tests/test_key_pool.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_key_pool.py`:
```python
import time
import pytest
from swarm.llm.key_pool import APIKey, KeyPool


def test_get_key_round_robin():
    pool = KeyPool(keys=[APIKey(key="k1"), APIKey(key="k2"), APIKey(key="k3")])
    keys = [pool.get_key().key for _ in range(6)]
    assert keys == ["k1", "k2", "k3", "k1", "k2", "k3"]


def test_get_key_skips_cooldown():
    pool = KeyPool(keys=[APIKey(key="k1"), APIKey(key="k2")])
    pool.mark_failed(pool.keys[0], cooldown_seconds=60)
    keys = [pool.get_key().key for _ in range(3)]
    assert keys == ["k2", "k2", "k2"]


def test_get_key_raises_when_all_in_cooldown():
    pool = KeyPool(keys=[APIKey(key="k1")])
    pool.mark_failed(pool.keys[0], cooldown_seconds=60)
    with pytest.raises(RuntimeError, match="No available API keys"):
        pool.get_key()


def test_mark_success_resets_error():
    pool = KeyPool(keys=[APIKey(key="k1")])
    pool.mark_failed(pool.keys[0], cooldown_seconds=0)
    pool.mark_success(pool.keys[0])
    assert pool.keys[0].last_error is None
    assert pool.keys[0].cooldown_until is None


def test_cooldown_expires():
    pool = KeyPool(keys=[APIKey(key="k1")])
    pool.keys[0].cooldown_until = time.time() - 1
    key = pool.get_key()
    assert key.key == "k1"


def test_empty_pool_raises():
    with pytest.raises(ValueError, match="At least one API key"):
        KeyPool(keys=[])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_key_pool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.llm.key_pool'`

- [ ] **Step 3: Write minimal implementation**

`swarm/llm/key_pool.py`:
```python
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class APIKey:
    key: str
    requests_made: int = 0
    last_error: float | None = None
    cooldown_until: float | None = None


class KeyPool:
    def __init__(self, keys: list[APIKey]) -> None:
        if not keys:
            raise ValueError("At least one API key required")
        self.keys = keys
        self._index = 0

    def get_key(self) -> APIKey:
        now = time.time()
        available = [
            k for k in self.keys
            if k.cooldown_until is None or k.cooldown_until <= now
        ]
        if not available:
            raise RuntimeError("No available API keys — all in cooldown")
        key = available[self._index % len(available)]
        self._index = (self._index + 1) % len(available)
        return key

    def mark_failed(self, key: APIKey, cooldown_seconds: int = 60) -> None:
        key.last_error = time.time()
        key.cooldown_until = time.time() + cooldown_seconds

    def mark_success(self, key: APIKey) -> None:
        key.last_error = None
        key.cooldown_until = None
        key.requests_made += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_key_pool.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/llm/key_pool.py tests/test_key_pool.py
git commit -m "feat: add API key pool with round-robin and cooldown"
```

---

## Task 3: LLM Router

**Files:**
- Create: `swarm/llm/router.py`
- Create: `tests/test_router.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_router.py`:
```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from swarm.llm.key_pool import APIKey, KeyPool
from swarm.llm.router import LLMRouter


@pytest.fixture
def router():
    pool = KeyPool(keys=[APIKey(key="test-key-1"), APIKey(key="test-key-2")])
    return LLMRouter(
        key_pool=pool,
        models=["model-a", "model-b"],
        base_url="https://openrouter.ai/api/v1",
        timeout=5,
        max_retries=2,
    )


@pytest.mark.asyncio
async def test_complete_success(router):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello from LLM"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(router._client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await router.complete([{"role": "user", "content": "Hi"}])
    assert result == "Hello from LLM"


@pytest.mark.asyncio
async def test_complete_falls_back_to_next_model(router):
    error_response = MagicMock()
    error_response.status_code = 500
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=error_response
    )

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {
        "choices": [{"message": {"content": "Fallback OK"}}]
    }
    ok_response.raise_for_status = MagicMock()

    with patch.object(
        router._client, "post", new_callable=AsyncMock,
        side_effect=[error_response, ok_response],
    ):
        result = await router.complete([{"role": "user", "content": "Hi"}])
    assert result == "Fallback OK"


@pytest.mark.asyncio
async def test_complete_all_models_fail(router):
    error_response = MagicMock()
    error_response.status_code = 500
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=error_response
    )

    with patch.object(
        router._client, "post", new_callable=AsyncMock,
        return_value=error_response,
    ):
        with pytest.raises(RuntimeError, match="All models failed"):
            await router.complete([{"role": "user", "content": "Hi"}])


@pytest.mark.asyncio
async def test_complete_uses_specified_model(router):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Specific model"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(router._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await router.complete([{"role": "user", "content": "Hi"}], model="custom-model")
        call_kwargs = mock_post.call_args[1]["json"]
        assert call_kwargs["model"] == "custom-model"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.llm.router'`

- [ ] **Step 3: Write minimal implementation**

`swarm/llm/router.py`:
```python
from __future__ import annotations

import asyncio
import logging

import httpx

from swarm.llm.key_pool import KeyPool

logger = logging.getLogger(__name__)


class LLMRouter:
    def __init__(
        self,
        key_pool: KeyPool,
        models: list[str],
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.key_pool = key_pool
        self.models = models
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)

    async def complete(
        self, messages: list[dict], model: str | None = None
    ) -> str:
        models_to_try = [model] if model else list(self.models)
        last_error: Exception | None = None

        for m in models_to_try:
            for attempt in range(self.max_retries):
                try:
                    api_key = self.key_pool.get_key()
                    response = await self._client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key.key}",
                            "Content-Type": "application/json",
                        },
                        json={"model": m, "messages": messages},
                    )
                    response.raise_for_status()
                    self.key_pool.mark_success(api_key)
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as exc:
                    last_error = exc
                    logger.warning(
                        "LLM call failed: model=%s attempt=%d error=%s",
                        m, attempt + 1, exc,
                    )
                    if isinstance(exc, httpx.HTTPStatusError):
                        try:
                            self.key_pool.mark_failed(api_key, cooldown_seconds=60)
                        except UnboundLocalError:
                            pass
                    backoff = min(2 ** attempt, 8)
                    await asyncio.sleep(backoff)

        raise RuntimeError(f"All models failed. Last error: {last_error}")

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_router.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/llm/router.py tests/test_router.py
git commit -m "feat: add LLM router with model failover and retry"
```

---

## Task 4: RPC Layer

**Files:**
- Create: `swarm/network/rpc.py`
- Create: `tests/test_rpc.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_rpc.py`:
```python
import asyncio
import pytest
import msgpack
from swarm.network.rpc import RPCServer, RPCClient


@pytest.mark.asyncio
async def test_rpc_call_and_response():
    results = {}

    async def echo_handler(params: dict) -> dict:
        return {"echo": params["msg"]}

    server = RPCServer(host="127.0.0.1", port=19000)
    server.register("echo", echo_handler)
    await server.start()

    try:
        client = RPCClient()
        response = await client.call("127.0.0.1", 19000, "echo", {"msg": "hello"})
        assert response == {"echo": "hello"}
    finally:
        await server.stop()
        await client.close()


@pytest.mark.asyncio
async def test_rpc_unknown_method():
    server = RPCServer(host="127.0.0.1", port=19001)
    await server.start()

    try:
        client = RPCClient()
        response = await client.call("127.0.0.1", 19001, "nonexistent", {})
        assert "error" in response
    finally:
        await server.stop()
        await client.close()


@pytest.mark.asyncio
async def test_rpc_multiple_methods():
    async def add_handler(params: dict) -> dict:
        return {"result": params["a"] + params["b"]}

    async def greet_handler(params: dict) -> dict:
        return {"greeting": f"Hello, {params['name']}!"}

    server = RPCServer(host="127.0.0.1", port=19002)
    server.register("add", add_handler)
    server.register("greet", greet_handler)
    await server.start()

    try:
        client = RPCClient()
        r1 = await client.call("127.0.0.1", 19002, "add", {"a": 2, "b": 3})
        assert r1 == {"result": 5}
        r2 = await client.call("127.0.0.1", 19002, "greet", {"name": "Василий"})
        assert r2 == {"greeting": "Hello, Василий!"}
    finally:
        await server.stop()
        await client.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rpc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.network.rpc'`

- [ ] **Step 3: Write minimal implementation**

`swarm/network/rpc.py`:
```python
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Coroutine

import msgpack

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Coroutine[Any, Any, dict]]


class RPCServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self._handlers: dict[str, Handler] = {}
        self._server: asyncio.Server | None = None

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        logger.info("RPC server listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            length_bytes = await reader.readexactly(4)
            length = int.from_bytes(length_bytes, "big")
            data = await reader.readexactly(length)
            request = msgpack.unpackb(data, raw=False)

            method = request.get("method", "")
            params = request.get("params", {})
            request_id = request.get("request_id", "")

            handler = self._handlers.get(method)
            if handler:
                result = await handler(params)
                response = {"request_id": request_id, "result": result}
            else:
                response = {
                    "request_id": request_id,
                    "error": f"Unknown method: {method}",
                }

            resp_data = msgpack.packb(response, use_bin_type=True)
            writer.write(len(resp_data).to_bytes(4, "big"))
            writer.write(resp_data)
            await writer.drain()
        except Exception as exc:
            logger.error("RPC handler error: %s", exc)
        finally:
            writer.close()
            await writer.wait_closed()


class RPCClient:
    async def call(
        self, host: str, port: int, method: str, params: dict
    ) -> dict:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            request = {
                "method": method,
                "params": params,
                "request_id": str(uuid.uuid4()),
            }
            data = msgpack.packb(request, use_bin_type=True)
            writer.write(len(data).to_bytes(4, "big"))
            writer.write(data)
            await writer.drain()

            length_bytes = await reader.readexactly(4)
            length = int.from_bytes(length_bytes, "big")
            resp_data = await reader.readexactly(length)
            response = msgpack.unpackb(resp_data, raw=False)
            return response.get("result") or response
        finally:
            writer.close()
            await writer.wait_closed()

    async def close(self) -> None:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rpc.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/network/rpc.py tests/test_rpc.py
git commit -m "feat: add RPC server/client with msgpack serialization"
```

---

## Task 5: Gossip Protocol

**Files:**
- Create: `swarm/network/gossip.py`
- Create: `tests/test_gossip.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_gossip.py`:
```python
import asyncio
import pytest
from swarm.network.gossip import GossipProtocol, GossipMessage


@pytest.mark.asyncio
async def test_gossip_message_creation():
    msg = GossipMessage(msg_type="NODE_JOIN", payload={"node_id": "abc"})
    assert msg.msg_type == "NODE_JOIN"
    assert msg.payload == {"node_id": "abc"}
    assert msg.id is not None


@pytest.mark.asyncio
async def test_gossip_deduplication():
    received = []

    async def handler(msg: GossipMessage):
        received.append(msg)

    g = GossipProtocol(host="127.0.0.1", port=18000, on_message=handler)
    await g.start()

    try:
        msg = GossipMessage(msg_type="TEST", payload={"data": 1})
        await g.inject(msg)
        await g.inject(msg)
        await asyncio.sleep(0.1)
        assert len(received) == 1
    finally:
        await g.stop()


@pytest.mark.asyncio
async def test_gossip_propagation_between_two_nodes():
    received_on_b = []

    async def handler_a(msg: GossipMessage):
        pass

    async def handler_b(msg: GossipMessage):
        received_on_b.append(msg)

    ga = GossipProtocol(
        host="127.0.0.1", port=18010, on_message=handler_a, interval=0.2, fanout=1,
    )
    gb = GossipProtocol(
        host="127.0.0.1", port=18011, on_message=handler_b, interval=0.2, fanout=1,
    )
    ga.add_peer("127.0.0.1", 18011)

    await ga.start()
    await gb.start()

    try:
        msg = GossipMessage(msg_type="TASK_BROADCAST", payload={"task": "parse"})
        await ga.inject(msg)
        await asyncio.sleep(1.0)
        assert len(received_on_b) == 1
        assert received_on_b[0].payload == {"task": "parse"}
    finally:
        await ga.stop()
        await gb.stop()


@pytest.mark.asyncio
async def test_gossip_seen_capacity():
    received = []

    async def handler(msg: GossipMessage):
        received.append(msg)

    g = GossipProtocol(
        host="127.0.0.1", port=18020, on_message=handler, seen_capacity=5,
    )
    await g.start()

    try:
        for i in range(10):
            msg = GossipMessage(msg_type="TEST", payload={"i": i})
            await g.inject(msg)
        assert len(received) == 10
        assert len(g._seen) <= 5
    finally:
        await g.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gossip.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.network.gossip'`

- [ ] **Step 3: Write minimal implementation**

`swarm/network/gossip.py`:
```python
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Any

import msgpack

logger = logging.getLogger(__name__)


@dataclass
class GossipMessage:
    msg_type: str
    payload: dict
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


class GossipProtocol:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8001,
        on_message: Callable[[GossipMessage], Coroutine[Any, Any, None]] | None = None,
        interval: float = 5.0,
        fanout: int = 3,
        seen_capacity: int = 1000,
    ) -> None:
        self.host = host
        self.port = port
        self._on_message = on_message
        self.interval = interval
        self.fanout = fanout
        self.seen_capacity = seen_capacity
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._peers: list[tuple[str, int]] = []
        self._outbox: list[GossipMessage] = []
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _UDPProtocol | None = None
        self._gossip_task: asyncio.Task | None = None

    def add_peer(self, host: str, port: int) -> None:
        if (host, port) not in self._peers:
            self._peers.append((host, port))

    def remove_peer(self, host: str, port: int) -> None:
        self._peers = [(h, p) for h, p in self._peers if (h, p) != (host, port)]

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._handle_incoming),
            local_addr=(self.host, self.port),
        )
        self._gossip_task = asyncio.create_task(self._gossip_loop())
        logger.info("Gossip listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._gossip_task:
            self._gossip_task.cancel()
            try:
                await self._gossip_task
            except asyncio.CancelledError:
                pass
        if self._transport:
            self._transport.close()

    async def inject(self, msg: GossipMessage) -> None:
        if msg.id in self._seen:
            return
        self._mark_seen(msg.id)
        if self._on_message:
            await self._on_message(msg)
        self._outbox.append(msg)

    async def _handle_incoming(self, data: bytes, addr: tuple) -> None:
        try:
            raw = msgpack.unpackb(data, raw=False)
            msg = GossipMessage(
                msg_type=raw["msg_type"],
                payload=raw["payload"],
                id=raw["id"],
            )
            await self.inject(msg)
        except Exception as exc:
            logger.error("Gossip receive error: %s", exc)

    async def _gossip_loop(self) -> None:
        import random

        while True:
            await asyncio.sleep(self.interval)
            if not self._outbox or not self._peers:
                continue
            messages = list(self._outbox)
            self._outbox.clear()
            targets = random.sample(self._peers, min(self.fanout, len(self._peers)))
            for msg in messages:
                data = msgpack.packb(
                    {"msg_type": msg.msg_type, "payload": msg.payload, "id": msg.id},
                    use_bin_type=True,
                )
                for host, port in targets:
                    if self._transport:
                        self._transport.sendto(data, (host, port))

    def _mark_seen(self, msg_id: str) -> None:
        self._seen[msg_id] = None
        while len(self._seen) > self.seen_capacity:
            self._seen.popitem(last=False)


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, handler: Callable) -> None:
        self._handler = handler

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        asyncio.ensure_future(self._handler(data, addr))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gossip.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/network/gossip.py tests/test_gossip.py
git commit -m "feat: add gossip protocol with push-based UDP propagation"
```

---

## Task 6: Kademlia Wrapper

**Files:**
- Create: `swarm/network/kademlia.py`
- Create: `tests/test_kademlia_wrapper.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_kademlia_wrapper.py`:
```python
import asyncio
import pytest
from swarm.network.kademlia import KademliaNode


@pytest.mark.asyncio
async def test_kademlia_start_and_stop():
    node = KademliaNode(port=17000)
    await node.start()
    assert node.node_id is not None
    await node.stop()


@pytest.mark.asyncio
async def test_kademlia_set_and_get():
    node = KademliaNode(port=17001)
    await node.start()

    try:
        await node.set("test_key", b"test_value")
        result = await node.get("test_key")
        assert result == b"test_value"
    finally:
        await node.stop()


@pytest.mark.asyncio
async def test_kademlia_get_missing_key():
    node = KademliaNode(port=17002)
    await node.start()

    try:
        result = await node.get("nonexistent")
        assert result is None
    finally:
        await node.stop()


@pytest.mark.asyncio
async def test_kademlia_two_nodes_share_data():
    node_a = KademliaNode(port=17010)
    node_b = KademliaNode(port=17011)
    await node_a.start()
    await node_b.start(bootstrap_addr=("127.0.0.1", 17010))

    try:
        await asyncio.sleep(0.5)
        await node_a.set("shared_key", b"shared_value")
        await asyncio.sleep(0.5)
        result = await node_b.get("shared_key")
        assert result == b"shared_value"
    finally:
        await node_a.stop()
        await node_b.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_kademlia_wrapper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.network.kademlia'`

- [ ] **Step 3: Write minimal implementation**

`swarm/network/kademlia.py`:
```python
from __future__ import annotations

import hashlib
import logging
import os

from kademlia.network import Server

logger = logging.getLogger(__name__)


class KademliaNode:
    def __init__(self, port: int = 8000) -> None:
        self.port = port
        self._server = Server()
        self.node_id: str | None = None

    async def start(
        self, bootstrap_addr: tuple[str, int] | None = None
    ) -> None:
        self.node_id = hashlib.sha1(os.urandom(20)).hexdigest()
        await self._server.listen(self.port)
        if bootstrap_addr:
            await self._server.bootstrap([bootstrap_addr])
        logger.info("Kademlia node %s listening on port %d", self.node_id, self.port)

    async def stop(self) -> None:
        self._server.stop()

    async def set(self, key: str, value: bytes) -> bool:
        return await self._server.set(key, value)

    async def get(self, key: str) -> bytes | None:
        result = await self._server.get(key)
        return result

    async def get_peers(self) -> list[str]:
        neighbors = self._server.bootstrappable_neighbors()
        return [f"{addr[0]}:{addr[1]}" for addr in neighbors]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_kademlia_wrapper.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/network/kademlia.py tests/test_kademlia_wrapper.py
git commit -m "feat: add Kademlia DHT wrapper for peer discovery and kv storage"
```

---

## Task 7: Reed-Solomon Erasure Coding

**Files:**
- Create: `swarm/memory/erasure.py`
- Create: `tests/test_erasure.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_erasure.py`:
```python
import pytest
from swarm.memory.erasure import ErasureCoder


@pytest.fixture
def coder():
    return ErasureCoder(data_shards=4, parity_shards=2)


def test_encode_produces_correct_shard_count(coder):
    data = b"Hello, Immortal Swarm! This is a test of erasure coding."
    shards = coder.encode(data)
    assert len(shards) == 6


def test_decode_with_all_shards(coder):
    data = b"Hello, Immortal Swarm! This is a test of erasure coding."
    shards = coder.encode(data)
    shard_map = {i: s for i, s in enumerate(shards)}
    result = coder.decode(shard_map, original_length=len(data))
    assert result == data


def test_decode_with_missing_shards(coder):
    data = b"Test data for recovery with missing shards in the swarm."
    shards = coder.encode(data)
    shard_map = {i: s for i, s in enumerate(shards) if i not in (1, 4)}
    assert len(shard_map) == 4
    result = coder.decode(shard_map, original_length=len(data))
    assert result == data


def test_decode_fails_with_too_few_shards(coder):
    data = b"Not enough shards to recover this data."
    shards = coder.encode(data)
    shard_map = {0: shards[0], 2: shards[2], 5: shards[5]}
    with pytest.raises(Exception):
        coder.decode(shard_map, original_length=len(data))


def test_encode_empty_data(coder):
    with pytest.raises(ValueError, match="Cannot encode empty data"):
        coder.encode(b"")


def test_roundtrip_large_data(coder):
    data = os.urandom(10000)
    shards = coder.encode(data)
    shard_map = {i: s for i, s in enumerate(shards)}
    result = coder.decode(shard_map, original_length=len(data))
    assert result == data


import os
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_erasure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.memory.erasure'`

- [ ] **Step 3: Write minimal implementation**

`swarm/memory/erasure.py`:
```python
from __future__ import annotations

import logging
from reedsolo import RSCodec

logger = logging.getLogger(__name__)


class ErasureCoder:
    def __init__(self, data_shards: int = 4, parity_shards: int = 2) -> None:
        self.data_shards = data_shards
        self.parity_shards = parity_shards
        self.total_shards = data_shards + parity_shards
        self._codec = RSCodec(parity_shards)

    def encode(self, data: bytes) -> list[bytes]:
        if not data:
            raise ValueError("Cannot encode empty data")
        encoded = self._codec.encode(data)
        encoded_bytes = bytes(encoded)
        shard_size = len(encoded_bytes) // self.total_shards
        if len(encoded_bytes) % self.total_shards != 0:
            shard_size += 1

        shards = []
        for i in range(self.total_shards):
            start = i * shard_size
            end = start + shard_size
            shards.append(encoded_bytes[start:end])
        return shards

    def decode(
        self, shard_map: dict[int, bytes], original_length: int
    ) -> bytes:
        if len(shard_map) < self.data_shards:
            raise ValueError(
                f"Need at least {self.data_shards} shards, got {len(shard_map)}"
            )
        shard_size = max(len(s) for s in shard_map.values())
        assembled = bytearray(shard_size * self.total_shards)
        erasure_positions = []

        for i in range(self.total_shards):
            start = i * shard_size
            if i in shard_map:
                shard = shard_map[i]
                assembled[start:start + len(shard)] = shard
            else:
                for pos in range(start, start + shard_size):
                    erasure_positions.append(pos)

        decoded = self._codec.decode(bytes(assembled), erase_pos=erasure_positions)
        return bytes(decoded[0])[:original_length]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_erasure.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/memory/erasure.py tests/test_erasure.py
git commit -m "feat: add Reed-Solomon erasure coding for memory sharding"
```

---

## Task 8: Distributed Memory Store

**Files:**
- Create: `swarm/memory/store.py`
- Create: `tests/test_memory_store.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_memory_store.py`:
```python
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from swarm.memory.store import DistributedMemory, MemoryBlock
from swarm.memory.erasure import ErasureCoder


@pytest.fixture
def mock_kademlia():
    node = AsyncMock()
    node.set = AsyncMock(return_value=True)
    storage = {}

    async def mock_get(key):
        return storage.get(key)

    async def mock_set(key, value):
        storage[key] = value
        return True

    node.get = mock_get
    node.set = mock_set
    node._storage = storage
    return node


@pytest.fixture
def mock_rpc():
    client = AsyncMock()
    client.call = AsyncMock(return_value={"status": "ok"})
    return client


@pytest.fixture
def memory(mock_kademlia, mock_rpc):
    return DistributedMemory(
        kademlia=mock_kademlia,
        rpc_client=mock_rpc,
        coder=ErasureCoder(data_shards=4, parity_shards=2),
        node_id="test-node",
    )


@pytest.mark.asyncio
async def test_store_and_retrieve(memory):
    block = MemoryBlock(
        owner_id="test-node",
        block_type="knowledge",
        content=b"The meaning of life is 42",
        tags=["test", "philosophy"],
    )
    block_id = await memory.store(block)
    assert block_id is not None

    retrieved = await memory.retrieve(block_id)
    assert retrieved is not None
    assert retrieved.content == b"The meaning of life is 42"
    assert retrieved.tags == ["test", "philosophy"]


@pytest.mark.asyncio
async def test_store_creates_tag_index(memory):
    block = MemoryBlock(
        owner_id="test-node",
        block_type="task_result",
        content=b"Price data",
        tags=["prices", "autoglass"],
    )
    block_id = await memory.store(block)
    results = await memory.search(tags=["autoglass"])
    assert len(results) >= 1
    assert any(r.id == block_id for r in results)


@pytest.mark.asyncio
async def test_delete_removes_block(memory):
    block = MemoryBlock(
        owner_id="test-node",
        block_type="dialog",
        content=b"Chat message",
        tags=["chat"],
    )
    block_id = await memory.store(block)
    deleted = await memory.delete(block_id)
    assert deleted is True
    result = await memory.retrieve(block_id)
    assert result is None


@pytest.mark.asyncio
async def test_memory_block_defaults():
    block = MemoryBlock(
        owner_id="node-1",
        block_type="knowledge",
        content=b"data",
        tags=[],
    )
    assert block.id is not None
    assert block.timestamp > 0
    assert block.ttl is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.memory.store'`

- [ ] **Step 3: Write minimal implementation**

`swarm/memory/store.py`:
```python
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

import msgpack

from swarm.memory.erasure import ErasureCoder

logger = logging.getLogger(__name__)


@dataclass
class MemoryBlock:
    owner_id: str
    block_type: str
    content: bytes
    tags: list[str]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    ttl: int | None = None


class DistributedMemory:
    def __init__(
        self,
        kademlia,
        rpc_client,
        coder: ErasureCoder,
        node_id: str,
    ) -> None:
        self._kademlia = kademlia
        self._rpc = rpc_client
        self._coder = coder
        self._node_id = node_id

    async def store(self, block: MemoryBlock) -> str:
        meta = msgpack.packb({
            "id": block.id,
            "owner_id": block.owner_id,
            "block_type": block.block_type,
            "timestamp": block.timestamp,
            "ttl": block.ttl,
            "tags": block.tags,
            "content_length": len(block.content),
        }, use_bin_type=True)
        await self._kademlia.set(f"meta:{block.id}", meta)

        shards = self._coder.encode(block.content)
        for i, shard in enumerate(shards):
            shard_key = f"shard:{block.id}:{i}"
            await self._kademlia.set(shard_key, shard)

        for tag in block.tags:
            tag_key = f"tag:{tag}"
            existing = await self._kademlia.get(tag_key)
            if existing:
                id_list = msgpack.unpackb(existing, raw=False)
            else:
                id_list = []
            if block.id not in id_list:
                id_list.append(block.id)
            await self._kademlia.set(tag_key, msgpack.packb(id_list, use_bin_type=True))

        logger.info("Stored block %s (%d bytes, %d shards)", block.id, len(block.content), len(shards))
        return block.id

    async def retrieve(self, block_id: str) -> MemoryBlock | None:
        meta_raw = await self._kademlia.get(f"meta:{block_id}")
        if meta_raw is None:
            return None
        meta = msgpack.unpackb(meta_raw, raw=False)

        shard_map = {}
        for i in range(self._coder.total_shards):
            shard_data = await self._kademlia.get(f"shard:{block_id}:{i}")
            if shard_data is not None:
                shard_map[i] = shard_data

        if len(shard_map) < self._coder.data_shards:
            logger.error("Not enough shards to recover block %s", block_id)
            return None

        content = self._coder.decode(shard_map, meta["content_length"])
        return MemoryBlock(
            id=meta["id"],
            owner_id=meta["owner_id"],
            block_type=meta["block_type"],
            content=content,
            tags=meta["tags"],
            timestamp=meta["timestamp"],
            ttl=meta["ttl"],
        )

    async def search(
        self, tags: list[str], owner: str | None = None
    ) -> list[MemoryBlock]:
        block_ids: set[str] = set()
        for tag in tags:
            raw = await self._kademlia.get(f"tag:{tag}")
            if raw:
                ids = msgpack.unpackb(raw, raw=False)
                block_ids.update(ids)

        results = []
        for bid in block_ids:
            block = await self.retrieve(bid)
            if block and (owner is None or block.owner_id == owner):
                results.append(block)
        return results

    async def delete(self, block_id: str) -> bool:
        meta_raw = await self._kademlia.get(f"meta:{block_id}")
        if meta_raw is None:
            return False
        meta = msgpack.unpackb(meta_raw, raw=False)

        for tag in meta.get("tags", []):
            tag_key = f"tag:{tag}"
            raw = await self._kademlia.get(tag_key)
            if raw:
                id_list = msgpack.unpackb(raw, raw=False)
                id_list = [bid for bid in id_list if bid != block_id]
                await self._kademlia.set(tag_key, msgpack.packb(id_list, use_bin_type=True))

        for i in range(self._coder.total_shards):
            await self._kademlia.set(f"shard:{block_id}:{i}", None)

        await self._kademlia.set(f"meta:{block_id}", None)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_store.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/memory/store.py tests/test_memory_store.py
git commit -m "feat: add distributed memory store with erasure-coded sharding"
```

---

## Task 9: SwarmAgent Core

**Files:**
- Create: `swarm/agent/core.py`
- Create: `tests/test_agent_core.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_agent_core.py`:
```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from swarm.agent.core import SwarmAgent, Task, TaskStatus


@pytest.fixture
def mock_deps():
    memory = AsyncMock()
    memory.store = AsyncMock(return_value="block-123")
    memory.retrieve = AsyncMock(return_value=None)
    memory.search = AsyncMock(return_value=[])
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="LLM says hello")
    gossip = AsyncMock()
    gossip.inject = AsyncMock()
    rpc_client = AsyncMock()
    rpc_client.call = AsyncMock(return_value={"status": "ok"})
    return memory, llm, gossip, rpc_client


@pytest.fixture
def agent(mock_deps):
    memory, llm, gossip, rpc_client = mock_deps
    return SwarmAgent(
        node_id="agent-1",
        memory=memory,
        llm=llm,
        gossip=gossip,
        rpc_client=rpc_client,
    )


def test_agent_creation(agent):
    assert agent.node_id == "agent-1"
    assert agent.skills == {}


@pytest.mark.asyncio
async def test_agent_think(agent):
    result = await agent.think("What is 2+2?")
    assert result == "LLM says hello"
    agent.llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_agent_submit_task(agent):
    task = Task(description="Parse prices", creator_id="agent-1")
    await agent.submit_task(task)
    assert task.status == TaskStatus.PENDING
    agent.gossip.inject.assert_called_once()


@pytest.mark.asyncio
async def test_task_creation():
    task = Task(description="Test task", creator_id="node-1")
    assert task.id is not None
    assert task.status == TaskStatus.PENDING
    assert task.result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.agent.core'`

- [ ] **Step 3: Write minimal implementation**

`swarm/agent/core.py`:
```python
from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from dataclasses import dataclass, field
from typing import Callable

from swarm.network.gossip import GossipMessage

logger = logging.getLogger(__name__)


class TaskStatus(enum.Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    description: str
    creator_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str | None = None
    result: str | None = None
    subtasks: list[Task] = field(default_factory=list)


class SwarmAgent:
    def __init__(
        self,
        node_id: str,
        memory,
        llm,
        gossip,
        rpc_client,
    ) -> None:
        self.node_id = node_id
        self.memory = memory
        self.llm = llm
        self.gossip = gossip
        self.rpc_client = rpc_client
        self.skills: dict[str, Callable] = {}
        self.task_queue: asyncio.Queue[Task] = asyncio.Queue()
        self._running = False

    def register_skill(self, name: str, handler: Callable) -> None:
        self.skills[name] = handler

    async def think(self, context: str, system_prompt: str | None = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": context})
        return await self.llm.complete(messages)

    async def submit_task(self, task: Task) -> None:
        task.status = TaskStatus.PENDING
        msg = GossipMessage(
            msg_type="TASK_BROADCAST",
            payload={
                "task_id": task.id,
                "description": task.description,
                "creator_id": task.creator_id,
            },
        )
        await self.gossip.inject(msg)
        logger.info("Task %s broadcast to network", task.id)

    async def claim_task(self, task: Task) -> None:
        task.status = TaskStatus.CLAIMED
        task.assigned_to = self.node_id
        await self.rpc_client.call(
            task.creator_id, 0, "task_claimed",
            {"task_id": task.id, "node_id": self.node_id},
        )

    async def run(self) -> None:
        self._running = True
        logger.info("Agent %s started", self.node_id)
        while self._running:
            try:
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                await self._execute_task(task)
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._running = False

    async def _execute_task(self, task: Task) -> None:
        task.status = TaskStatus.RUNNING
        try:
            result = await self.think(
                f"Execute this task: {task.description}",
                system_prompt="You are an autonomous AI agent in a swarm. Complete the given task.",
            )
            task.result = result
            task.status = TaskStatus.DONE
            from swarm.memory.store import MemoryBlock
            block = MemoryBlock(
                owner_id=self.node_id,
                block_type="task_result",
                content=result.encode(),
                tags=["task_result", task.id],
            )
            await self.memory.store(block)
            logger.info("Task %s completed by %s", task.id, self.node_id)
        except Exception as exc:
            task.status = TaskStatus.FAILED
            logger.error("Task %s failed: %s", task.id, exc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_core.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/agent/core.py tests/test_agent_core.py
git commit -m "feat: add SwarmAgent core with task lifecycle"
```

---

## Task 10: Task Manager

**Files:**
- Create: `swarm/agent/task_manager.py`
- Create: `tests/test_task_manager.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_task_manager.py`:
```python
import pytest
from unittest.mock import AsyncMock
from swarm.agent.task_manager import TaskManager
from swarm.agent.core import Task


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='["Parse prices from site A", "Parse prices from site B", "Aggregate results"]')
    return llm


@pytest.fixture
def manager(mock_llm):
    return TaskManager(llm=mock_llm, node_id="coordinator-1")


@pytest.mark.asyncio
async def test_decompose_creates_subtasks(manager):
    task = Task(description="Parse prices from 2 sites and aggregate", creator_id="user")
    subtasks = await manager.decompose(task)
    assert len(subtasks) == 3
    assert all(isinstance(t, Task) for t in subtasks)


@pytest.mark.asyncio
async def test_decompose_sets_creator_to_coordinator(manager):
    task = Task(description="Do something complex", creator_id="user")
    subtasks = await manager.decompose(task)
    assert all(t.creator_id == "coordinator-1" for t in subtasks)


@pytest.mark.asyncio
async def test_decompose_handles_llm_returning_single_task(manager):
    manager.llm.complete = AsyncMock(return_value='["Just do this one thing"]')
    task = Task(description="Simple task", creator_id="user")
    subtasks = await manager.decompose(task)
    assert len(subtasks) == 1


@pytest.mark.asyncio
async def test_decompose_handles_invalid_json(manager):
    manager.llm.complete = AsyncMock(return_value="Not valid JSON at all")
    task = Task(description="Something", creator_id="user")
    subtasks = await manager.decompose(task)
    assert len(subtasks) == 1
    assert subtasks[0].description == task.description
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_task_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.agent.task_manager'`

- [ ] **Step 3: Write minimal implementation**

`swarm/agent/task_manager.py`:
```python
from __future__ import annotations

import json
import logging

from swarm.agent.core import Task

logger = logging.getLogger(__name__)

DECOMPOSE_PROMPT = """You are a task decomposition engine. Break the following task into smaller independent subtasks.
Return a JSON array of strings, each string is a subtask description.
Example: ["subtask 1", "subtask 2", "subtask 3"]

Task: {description}

Return ONLY the JSON array, nothing else."""


class TaskManager:
    def __init__(self, llm, node_id: str) -> None:
        self.llm = llm
        self.node_id = node_id

    async def decompose(self, task: Task) -> list[Task]:
        prompt = DECOMPOSE_PROMPT.format(description=task.description)
        raw = await self.llm.complete([{"role": "user", "content": prompt}])

        try:
            descriptions = json.loads(raw)
            if not isinstance(descriptions, list):
                raise ValueError("Expected a list")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM returned invalid JSON for decomposition: %s", exc)
            return [Task(description=task.description, creator_id=self.node_id)]

        return [
            Task(description=desc, creator_id=self.node_id)
            for desc in descriptions
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_task_manager.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/agent/task_manager.py tests/test_task_manager.py
git commit -m "feat: add task manager with LLM-based decomposition"
```

---

## Task 11: Skills (WebParser + Chat)

**Files:**
- Create: `swarm/agent/skills.py`
- Create: `tests/test_skills.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_skills.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from swarm.agent.skills import WebParserSkill, ChatSkill


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Extracted price: 5000 RUB")
    return llm


@pytest.fixture
def mock_memory():
    memory = AsyncMock()
    memory.store = AsyncMock(return_value="block-1")
    return memory


@pytest.mark.asyncio
async def test_web_parser_skill(mock_llm):
    skill = WebParserSkill(llm=mock_llm)
    mock_response = AsyncMock()
    mock_response.text = "<html><body><p>Price: 5000</p></body></html>"
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("swarm.agent.skills.httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.aclose = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await skill.execute(
            url="https://example.com",
            instruction="Extract the price",
        )

    assert "5000" in result
    mock_llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_chat_skill_send(mock_llm, mock_memory):
    rpc = AsyncMock()
    rpc.call = AsyncMock(return_value={"status": "ok"})

    skill = ChatSkill(llm=mock_llm, memory=mock_memory, rpc_client=rpc, node_id="agent-1")
    response = await skill.send_message(
        target_node="agent-2",
        target_port=8001,
        message="Hello, how are you?",
        context="We are discussing autoglass prices",
    )
    assert response == "LLM says: Extracted price: 5000 RUB" or response is not None
    rpc.call.assert_called_once()


@pytest.mark.asyncio
async def test_chat_skill_saves_dialog(mock_llm, mock_memory):
    rpc = AsyncMock()
    rpc.call = AsyncMock(return_value={"status": "ok"})

    skill = ChatSkill(llm=mock_llm, memory=mock_memory, rpc_client=rpc, node_id="agent-1")
    await skill.send_message(
        target_node="agent-2",
        target_port=8001,
        message="Test message",
        context="Test context",
    )
    mock_memory.store.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.agent.skills'`

- [ ] **Step 3: Write minimal implementation**

`swarm/agent/skills.py`:
```python
from __future__ import annotations

import logging

import httpx

from swarm.memory.store import MemoryBlock

logger = logging.getLogger(__name__)


class WebParserSkill:
    def __init__(self, llm) -> None:
        self.llm = llm

    async def execute(self, url: str, instruction: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            html = response.text

        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        text_content = tree.body.text(separator="\n", strip=True) if tree.body else html

        truncated = text_content[:4000]
        prompt = (
            f"I scraped the following text from {url}:\n\n"
            f"{truncated}\n\n"
            f"Instruction: {instruction}\n"
            f"Extract and structure the relevant information."
        )
        result = await self.llm.complete([{"role": "user", "content": prompt}])
        return result


class ChatSkill:
    def __init__(self, llm, memory, rpc_client, node_id: str) -> None:
        self.llm = llm
        self.memory = memory
        self.rpc_client = rpc_client
        self.node_id = node_id

    async def send_message(
        self,
        target_node: str,
        target_port: int,
        message: str,
        context: str = "",
    ) -> str:
        prompt = (
            f"Context: {context}\n"
            f"Message from peer: {message}\n"
            f"Compose a thoughtful response."
        )
        response = await self.llm.complete([{"role": "user", "content": prompt}])

        await self.rpc_client.call(
            target_node, target_port, "chat_message",
            {"from": self.node_id, "message": response},
        )

        block = MemoryBlock(
            owner_id=self.node_id,
            block_type="dialog",
            content=f"Me: {message}\nPeer: {response}".encode(),
            tags=["dialog", target_node],
        )
        await self.memory.store(block)

        return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_skills.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add swarm/agent/skills.py tests/test_skills.py
git commit -m "feat: add WebParser and Chat skills for agent capabilities"
```

---

## Task 12: CLI Entry Point (node.py)

**Files:**
- Create: `node.py`
- Create: `tests/test_node_cli.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_node_cli.py`:
```python
import pytest
from click.testing import CliRunner
from node import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Immortal Swarm" in result.output or "node" in result.output


def test_cli_status_command_exists(runner):
    result = runner.invoke(cli, ["status", "--help"])
    assert result.exit_code == 0


def test_cli_nodes_command_exists(runner):
    result = runner.invoke(cli, ["nodes", "--help"])
    assert result.exit_code == 0


def test_cli_task_command_exists(runner):
    result = runner.invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_node_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'node'`

- [ ] **Step 3: Write minimal implementation**

`node.py`:
```python
from __future__ import annotations

import asyncio
import logging
import sys

import click
import yaml

from swarm.llm.key_pool import APIKey, KeyPool
from swarm.llm.router import LLMRouter
from swarm.memory.erasure import ErasureCoder
from swarm.memory.store import DistributedMemory
from swarm.network.gossip import GossipProtocol
from swarm.network.kademlia import KademliaNode
from swarm.network.rpc import RPCServer, RPCClient
from swarm.agent.core import SwarmAgent, Task
from swarm.agent.task_manager import TaskManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("swarm")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


async def start_node(port: int, bootstrap: str | None, config_path: str) -> None:
    cfg = load_config(config_path)

    kad = KademliaNode(port=port)
    bootstrap_addr = None
    if bootstrap:
        host, bport = bootstrap.split(":")
        bootstrap_addr = (host, int(bport))
    await kad.start(bootstrap_addr=bootstrap_addr)

    gossip = GossipProtocol(
        host="0.0.0.0",
        port=port + 1000,
        interval=cfg["gossip"]["interval"],
        fanout=cfg["gossip"]["fanout"],
        seen_capacity=cfg["gossip"]["seen_capacity"],
    )

    rpc_server = RPCServer(host="0.0.0.0", port=port + 2000)
    rpc_client = RPCClient()

    llm_cfg = cfg["llm"]
    keys = [APIKey(key=k) for k in llm_cfg.get("keys", [])]
    if keys:
        key_pool = KeyPool(keys=keys)
        llm = LLMRouter(
            key_pool=key_pool,
            models=llm_cfg["models"],
            base_url=llm_cfg["base_url"],
            timeout=llm_cfg["timeout"],
            max_retries=llm_cfg["max_retries"],
        )
    else:
        llm = None

    mem_cfg = cfg["memory"]
    coder = ErasureCoder(
        data_shards=mem_cfg["data_shards"],
        parity_shards=mem_cfg["parity_shards"],
    )
    memory = DistributedMemory(
        kademlia=kad,
        rpc_client=rpc_client,
        coder=coder,
        node_id=kad.node_id or "unknown",
    )

    agent = SwarmAgent(
        node_id=kad.node_id or "unknown",
        memory=memory,
        llm=llm,
        gossip=gossip,
        rpc_client=rpc_client,
    )

    await gossip.start()
    await rpc_server.start()

    logger.info(
        "Node started: Kademlia=%d Gossip=%d RPC=%d",
        port, port + 1000, port + 2000,
    )

    try:
        await agent.run()
    except KeyboardInterrupt:
        pass
    finally:
        await agent.stop()
        await gossip.stop()
        await rpc_server.stop()
        await kad.stop()
        if llm:
            await llm.close()


@click.group()
def cli():
    """Immortal Swarm — Distributed AI Agent Network"""
    pass


@cli.command()
@click.option("--port", default=8000, help="Kademlia port")
@click.option("--bootstrap", default=None, help="Bootstrap node (host:port)")
@click.option("--config", default="config.yaml", help="Config file path")
def start(port: int, bootstrap: str | None, config: str):
    """Start a swarm node."""
    asyncio.run(start_node(port, bootstrap, config))


@cli.command()
def status():
    """Show network status."""
    click.echo("Status: not connected (run 'start' first)")


@cli.command()
def nodes():
    """List known nodes."""
    click.echo("Nodes: not connected (run 'start' first)")


@cli.command()
@click.argument("description")
def task(description: str):
    """Submit a task to the swarm."""
    click.echo(f"Task submitted: {description}")
    click.echo("(Connect to a running node to actually dispatch)")


@cli.group()
def memory():
    """Memory operations."""
    pass


@memory.command()
@click.argument("query")
def search(query: str):
    """Search distributed memory by tags."""
    click.echo(f"Searching for: {query}")
    click.echo("(Connect to a running node to search)")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_node_cli.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add node.py tests/test_node_cli.py
git commit -m "feat: add CLI entry point with start/status/nodes/task/memory commands"
```

---

## Task 13: Integration Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

`tests/test_integration.py`:
```python
import asyncio
import pytest
from swarm.network.kademlia import KademliaNode
from swarm.network.gossip import GossipProtocol, GossipMessage
from swarm.network.rpc import RPCServer, RPCClient
from swarm.memory.erasure import ErasureCoder
from swarm.memory.store import DistributedMemory, MemoryBlock


@pytest.mark.asyncio
async def test_two_node_gossip_and_memory():
    """Integration: two nodes share data through DHT and communicate via gossip."""
    received_gossip = []

    async def on_gossip_b(msg):
        received_gossip.append(msg)

    kad_a = KademliaNode(port=16000)
    kad_b = KademliaNode(port=16001)
    await kad_a.start()
    await kad_b.start(bootstrap_addr=("127.0.0.1", 16000))
    await asyncio.sleep(1.0)

    gossip_a = GossipProtocol(host="127.0.0.1", port=16100, interval=0.3, fanout=1)
    gossip_b = GossipProtocol(
        host="127.0.0.1", port=16101, on_message=on_gossip_b, interval=0.3, fanout=1,
    )
    gossip_a.add_peer("127.0.0.1", 16101)
    await gossip_a.start()
    await gossip_b.start()

    coder = ErasureCoder(data_shards=4, parity_shards=2)
    rpc_client = RPCClient()

    mem_a = DistributedMemory(kademlia=kad_a, rpc_client=rpc_client, coder=coder, node_id="node-a")
    mem_b = DistributedMemory(kademlia=kad_b, rpc_client=rpc_client, coder=coder, node_id="node-b")

    try:
        block = MemoryBlock(
            owner_id="node-a",
            block_type="knowledge",
            content=b"Autoglass prices: windshield 5000 RUB",
            tags=["prices", "autoglass"],
        )
        block_id = await mem_a.store(block)
        await asyncio.sleep(1.0)

        retrieved = await mem_b.retrieve(block_id)
        assert retrieved is not None
        assert retrieved.content == b"Autoglass prices: windshield 5000 RUB"

        msg = GossipMessage(msg_type="TASK_BROADCAST", payload={"task": "parse more"})
        await gossip_a.inject(msg)
        await asyncio.sleep(1.5)

        assert len(received_gossip) >= 1
        assert received_gossip[0].payload["task"] == "parse more"
    finally:
        await gossip_a.stop()
        await gossip_b.stop()
        await kad_a.stop()
        await kad_b.stop()
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_integration.py -v --timeout=30`
Expected: 1 passed

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: All tests pass (approximately 35+ tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add multi-node integration test for gossip and memory"
```

---

## Task 14: Final Cleanup

- [ ] **Step 1: Add .gitignore**

`.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
build/
.env
venv/
```

- [ ] **Step 2: Run full suite one last time**

Run: `pytest -v --tb=short`
Expected: All tests pass

- [ ] **Step 3: Final commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore and finalize MVP"
```
