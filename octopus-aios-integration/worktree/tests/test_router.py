import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm.llm.key_pool import APIKey, KeyPool
from swarm.llm.router import LLMRouter


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


@pytest.fixture
def router():
    pool = KeyPool(keys=[APIKey(key="test-key-1"), APIKey(key="test-key-2")])
    return LLMRouter(
        key_pool=pool,
        models=["model-a", "model-b"],
        base_url="https://openrouter.ai/api/v1",
        timeout=5,
        max_retries=2,
        backoff_base=0,
    )


@pytest.mark.asyncio
async def test_complete_success(router):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello from LLM"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(router._get_client(), "post", new_callable=AsyncMock, return_value=mock_response):
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

    with patch.object(router.key_pool, "mark_failed"), \
         patch.object(
            router._get_client(), "post", new_callable=AsyncMock,
            side_effect=[error_response, error_response, ok_response],
         ) as mock_post:
        result = await router.complete([{"role": "user", "content": "Hi"}])
    assert result == "Fallback OK"
    last_call_body = mock_post.call_args_list[-1][1]["json"]
    assert last_call_body["model"] == "model-b"


@pytest.mark.asyncio
async def test_complete_all_models_fail(router):
    error_response = MagicMock()
    error_response.status_code = 500
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=error_response
    )

    with patch.object(
        router._get_client(), "post", new_callable=AsyncMock,
        return_value=error_response,
    ), pytest.raises(RuntimeError, match="All models failed"):
        await router.complete([{"role": "user", "content": "Hi"}])


@pytest.mark.asyncio
async def test_complete_uses_specified_model(router):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Specific model"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(router._get_client(), "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await router.complete([{"role": "user", "content": "Hi"}], model="custom-model")
        call_kwargs = mock_post.call_args[1]["json"]
        assert call_kwargs["model"] == "custom-model"


def test_empty_models_raises():
    pool = KeyPool(keys=[APIKey(key="k")])
    with pytest.raises(ValueError, match="At least one model required"):
        LLMRouter(key_pool=pool, models=[])


@pytest.mark.asyncio
async def test_complete_falls_back_to_local_after_cloud_fails():
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=["cloud-model"],
        base_url="https://openrouter.example/api/v1",
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["gguf-model"],
        timeout=5,
        max_retries=1,
        backoff_base=0,
    )
    err = MagicMock()
    err.status_code = 500
    err.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=err
    )
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {
        "choices": [{"message": {"content": "local ok"}}]
    }
    ok.raise_for_status = MagicMock()

    with patch.object(r._get_client(), "post", new_callable=AsyncMock, side_effect=[err, ok]) as mp:
        out = await r.complete([{"role": "user", "content": "hi"}])
    assert out == "local ok"
    assert "openrouter.example" in mp.call_args_list[0][0][0]
    assert "127.0.0.1:8080" in mp.call_args_list[1][0][0]
    assert mp.call_args_list[1][1]["json"]["model"] == "gguf-model"
    await r.close()


@pytest.mark.asyncio
async def test_prefer_local_tries_local_first():
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=["cloud-model"],
        base_url="https://openrouter.example/api/v1",
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["L"],
        prefer_local=True,
        timeout=5,
        max_retries=1,
        backoff_base=0,
    )
    ok_local = MagicMock()
    ok_local.status_code = 200
    ok_local.json.return_value = {
        "choices": [{"message": {"content": "from local"}}]
    }
    ok_local.raise_for_status = MagicMock()

    with patch.object(r._get_client(), "post", new_callable=AsyncMock, return_value=ok_local) as mp:
        out = await r.complete([{"role": "user", "content": "hi"}])
    assert out == "from local"
    assert "127.0.0.1:8080" in mp.call_args[0][0]
    await r.close()


@pytest.mark.asyncio
async def test_local_without_api_key_omits_authorization_header():
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=[],
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["m"],
        prefer_local=True,
        timeout=5,
        max_retries=1,
        backoff_base=0,
    )
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"choices": [{"message": {"content": "x"}}]}
    ok.raise_for_status = MagicMock()

    with patch.object(r._get_client(), "post", new_callable=AsyncMock, return_value=ok) as mp:
        await r.complete([{"role": "user", "content": "z"}])
    hdrs = mp.call_args[1]["headers"]
    assert not any(str(k).lower() == "authorization" for k in hdrs)
    await r.close()


@pytest.mark.asyncio
async def test_model_alias_resolves_cloud_to_local():
    """Model alias maps a cloud name to the local model name."""
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=[],
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["llama-3.3-70b"],
        prefer_local=True,
        model_aliases={"meta-llama/llama-3.3-70b-instruct": "llama-3.3-70b"},
        timeout=5,
        max_retries=1,
        backoff_base=0,
    )
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"choices": [{"message": {"content": "aliased"}}]}
    ok.raise_for_status = MagicMock()

    with patch.object(r._get_client(), "post", new_callable=AsyncMock, return_value=ok) as mp:
        out = await r.complete(
            [{"role": "user", "content": "hi"}],
            model="meta-llama/llama-3.3-70b-instruct",
        )
    assert out == "aliased"
    # Should have sent the resolved local model name, not the cloud name
    sent_model = mp.call_args[1]["json"]["model"]
    assert sent_model == "llama-3.3-70b"
    await r.close()


@pytest.mark.asyncio
async def test_model_alias_not_applied_to_cloud():
    """Aliases only affect local targets — cloud targets keep original names."""
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=["meta-llama/llama-3.3-70b-instruct"],
        base_url="https://openrouter.example/api/v1",
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["llama-3.3-70b"],
        prefer_local=False,  # cloud first
        model_aliases={"meta-llama/llama-3.3-70b-instruct": "llama-3.3-70b"},
        timeout=5,
        max_retries=1,
        backoff_base=0,
    )
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"choices": [{"message": {"content": "cloud ok"}}]}
    ok.raise_for_status = MagicMock()

    with patch.object(r._get_client(), "post", new_callable=AsyncMock, return_value=ok) as mp:
        out = await r.complete([{"role": "user", "content": "hi"}])
    assert out == "cloud ok"
    # Cloud target should use the original name (no alias)
    sent_model = mp.call_args[1]["json"]["model"]
    assert sent_model == "meta-llama/llama-3.3-70b-instruct"
    await r.close()


@pytest.mark.asyncio
async def test_model_alias_cloud_fails_falls_back_to_aliased_local():
    """Cloud fails → falls back to local with alias resolution."""
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=["meta-llama/llama-3.3-70b-instruct"],
        base_url="https://openrouter.example/api/v1",
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["llama-3.3-70b"],
        prefer_local=False,
        model_aliases={"meta-llama/llama-3.3-70b-instruct": "llama-3.3-70b"},
        timeout=5,
        max_retries=1,
        backoff_base=0,
    )
    err = MagicMock()
    err.status_code = 500
    err.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=err
    )
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"choices": [{"message": {"content": "local fallback"}}]}
    ok.raise_for_status = MagicMock()

    with patch.object(r._get_client(), "post", new_callable=AsyncMock, side_effect=[err, ok]) as mp:
        out = await r.complete(
            [{"role": "user", "content": "hi"}],
            model="meta-llama/llama-3.3-70b-instruct",
        )
    assert out == "local fallback"
    # First call: cloud with original name
    assert mp.call_args_list[0][1]["json"]["model"] == "meta-llama/llama-3.3-70b-instruct"
    # Second call: local with aliased name
    assert mp.call_args_list[1][1]["json"]["model"] == "llama-3.3-70b"
    await r.close()


@pytest.mark.asyncio
async def test_no_aliases_behaves_same():
    """Without aliases, behavior is unchanged (regression check)."""
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=[],
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["my-model"],
        prefer_local=True,
        timeout=5,
        max_retries=1,
        backoff_base=0,
    )
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"choices": [{"message": {"content": "plain"}}]}
    ok.raise_for_status = MagicMock()

    with patch.object(r._get_client(), "post", new_callable=AsyncMock, return_value=ok) as mp:
        out = await r.complete([{"role": "user", "content": "hi"}])
    assert out == "plain"
    assert mp.call_args[1]["json"]["model"] == "my-model"
    await r.close()


def test_usage_snapshot_includes_aliases():
    pool = KeyPool(keys=[APIKey(key="k")])
    r = LLMRouter(
        key_pool=pool,
        models=["cloud"],
        local_base_url="http://127.0.0.1:8080/v1",
        local_models=["local"],
        model_aliases={"cloud": "local"},
    )
    snap = r.usage_snapshot()
    assert snap["model_aliases"] == {"cloud": "local"}
