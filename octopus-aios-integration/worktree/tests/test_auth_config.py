import pytest

from swarm.tools_runtime.api_kit.auth_config import ControlPlaneAuthConfig


def test_auth_config_requires_all_values(monkeypatch):
    for key in ("AIOS_OPERATOR_TOKEN", "AIOS_OPERATOR_ROLE", "AIOS_OPERATOR_ACTOR"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError):
        ControlPlaneAuthConfig.from_env()


def test_auth_config_rejects_weak_token(monkeypatch):
    monkeypatch.setenv("AIOS_OPERATOR_TOKEN", "short")
    monkeypatch.setenv("AIOS_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("AIOS_OPERATOR_ACTOR", "ci")
    with pytest.raises(RuntimeError):
        ControlPlaneAuthConfig.from_env()


def test_auth_config_accepts_valid_values(monkeypatch):
    monkeypatch.setenv("AIOS_OPERATOR_TOKEN", "0123456789abcdef")
    monkeypatch.setenv("AIOS_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("AIOS_OPERATOR_ACTOR", "ci")
    config = ControlPlaneAuthConfig.from_env()
    assert config.role == "operator"
    assert config.actor == "ci"
