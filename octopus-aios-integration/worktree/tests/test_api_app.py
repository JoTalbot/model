import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from swarm.tools_runtime.api_kit.app import create_app


def test_health_and_readiness():
    app = create_app(operator_validator=lambda request: True)
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok", "system": "AIOS"}
    assert client.get("/ready").json() == {"status": "ready", "system": "AIOS"}


def test_recovery_auth_receives_request():
    app = create_app(operator_validator=lambda request: request.headers.get("x-operator") == "1")
    client = TestClient(app)
    assert client.get("/recovery/queue").status_code == 403
    assert client.get("/recovery/queue", headers={"x-operator": "1"}).status_code == 200
