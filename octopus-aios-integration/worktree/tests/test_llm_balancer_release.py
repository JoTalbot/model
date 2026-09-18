import asyncio

import httpx
import pytest

from swarm.llm.balancer import (
    ArenaGatewayProvider,
    BaseLLMProvider,
    LLMBalancer,
    OpenAICompatibleCloudProvider,
)


class FakeProvider(BaseLLMProvider):
    def __init__(self, name="fake", tier="fast", result="ok", fail=False):
        self.name = name
        self.tier = tier
        self.weight = 1
        self.timeout_sec = 0.2
        self.result = result
        self.fail = fail

    async def generate(self, prompt, system=None):
        if self.fail:
            raise RuntimeError("boom")
        return self.result


@pytest.mark.asyncio
async def test_openai_compatible_provider_preserves_full_prompt(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

        text = ""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("swarm.llm.balancer.httpx.AsyncClient", FakeClient)
    provider = OpenAICompatibleCloudProvider(
        "fake", "https://example.invalid/v1", "model", ["test-key"], timeout=1
    )
    prompt = "USER-INSTRUCTION-" + ("x" * 12000)
    result = await provider.generate(prompt)
    assert result == "ok"
    assert captured["json"]["messages"][-1]["content"] == prompt


@pytest.mark.asyncio
async def test_balancer_falls_back_after_provider_failure():
    balancer = LLMBalancer.__new__(LLMBalancer)
    balancer.providers = [FakeProvider("broken", fail=True), FakeProvider("working", result="fallback")]
    balancer.cache = {}
    balancer.cache_ttl = 300
    result = await balancer.ask("hello", use_cache=False)
    assert result["text"] == "fallback"
    assert result["provider"] == "working"


@pytest.mark.asyncio
async def test_balancer_uses_emergency_engine_when_all_providers_fail():
    balancer = LLMBalancer.__new__(LLMBalancer)
    balancer.providers = [FakeProvider("broken", fail=True)]
    balancer.cache = {}
    balancer.cache_ttl = 300
    result = await balancer.ask("hello", use_cache=False)
    assert result["status"] == "success"
    assert result["provider"] == "emergency_engine"
    assert result["text"]


def test_arena_provider_is_strictly_tiered():
    provider = ArenaGatewayProvider("arena", "http://127.0.0.1:8791/v1", "model", ["k"])
    provider._health_cache = {"at": 10**20, "ok": True}
    provider.healthy = True
    assert provider.strict_tier is True
    assert provider.tier == "arena"


def test_legacy_import_is_canonical():
    from code.llm.balancer.llm_balancer import LLMBalancer as Legacy
    from swarm.llm.balancer import LLMBalancer as Canonical

    assert Legacy is Canonical
