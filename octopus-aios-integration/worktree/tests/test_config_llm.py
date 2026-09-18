"""Тесты для swarm.config.llm и swarm.bootstrap.config."""

import pytest

from swarm.bootstrap.config import load_config
from swarm.config.llm import LLMConfig, LocalLLMConfig


class TestLLMConfig:
    def test_defaults(self):
        cfg = LLMConfig.model_validate({})
        assert cfg.timeout == 120
        assert cfg.models == []
        assert cfg.local is None

    def test_full_config(self):
        cfg = LLMConfig.model_validate({
            "base_url": "https://openrouter.ai/api/v1",
            "keys": ["key1", "key2"],
            "models": ["model-a", "model-b"],
            "timeout": 30,
            "max_retries": 5,
        })
        assert cfg.base_url == "https://openrouter.ai/api/v1"
        assert len(cfg.keys) == 2
        assert cfg.max_retries == 5

    def test_legacy_normalization(self):
        """api_base → base_url, retries → max_retries."""
        cfg = LLMConfig.model_validate({
            "api_base": "https://example.com/v1",
            "retries": 7,
        })
        assert cfg.base_url == "https://example.com/v1"
        assert cfg.max_retries == 7

    def test_local_config(self):
        cfg = LLMConfig.model_validate({
            "local": {
                "enabled": True,
                "base_url": "http://127.0.0.1:8080/v1",
                "models": ["llama-3"],
                "prefer_local": True,
                "model_aliases": {"cloud-model": "llama-3"},
            }
        })
        assert cfg.local is not None
        assert cfg.local.enabled is True
        assert cfg.local.models == ["llama-3"]
        assert cfg.local.model_aliases == {"cloud-model": "llama-3"}


class TestLocalLLMConfig:
    def test_defaults(self):
        cfg = LocalLLMConfig.model_validate({})
        assert cfg.enabled is False
        assert cfg.models == []
        assert cfg.model_aliases == {}

    def test_with_aliases(self):
        cfg = LocalLLMConfig.model_validate({
            "enabled": True,
            "base_url": "http://localhost:8080/v1",
            "models": ["m1"],
            "model_aliases": {"a": "b"},
        })
        assert cfg.model_aliases == {"a": "b"}


class TestLoadConfig:
    def test_load_default(self):
        cfg = load_config("config.yaml")
        assert cfg["llm"] is not None
        assert cfg.get("node") is not None

    def test_load_missing_raises(self):
        with pytest.raises(Exception):
            load_config("nonexistent_file.yaml")
