"""Adapted (Wave 2): upstream test targeted the stale ``operator_validator -> bool``
API; ``main`` now exposes ``app = create_app(operator_validator=authenticate)``.
Intent preserved: bearer validation + app smoke.
"""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from swarm.tools_runtime.api_kit import main as main_module
from swarm.tools_runtime.api_kit.auth_config import ControlPlaneAuthConfig
from swarm.tools_runtime.api_kit.security import authenticate


def _cfg():
    return ControlPlaneAuthConfig(token="secret-0123456789", role="operator", actor="ci")


class _Request:
    def __init__(self, headers):
        self.headers = headers


def test_operator_validator_requires_bearer_token():
    req = _Request({"authorization": "Bearer secret-0123456789"})
    ctx = authenticate(req, _cfg())
    assert ctx is not None and ctx.actor == "ci"


def test_operator_validator_rejects_wrong_token():
    req = _Request({"authorization": "Bearer wrong"})
    assert authenticate(req, _cfg()) is None


def test_main_app_smoke():
    client = TestClient(main_module.app)
    assert client.get("/health").json() == {"status": "ok", "system": "AIOS"}
