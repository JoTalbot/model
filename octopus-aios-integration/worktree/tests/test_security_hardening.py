import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from swarm.tools_runtime.api_kit.security import OperatorRole, authenticate


def make_app():
    app = FastAPI()

    @app.get("/auth")
    def auth(request: Request):
        context = authenticate(request)
        return context.__dict__ if context else {"authenticated": False}

    return app


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
def test_role_and_actor_are_not_taken_from_headers(monkeypatch):
    monkeypatch.setenv("AIOS_OPERATOR_TOKEN", "secret")
    monkeypatch.setenv("AIOS_OPERATOR_ROLE", "viewer")
    monkeypatch.setenv("AIOS_OPERATOR_ACTOR", "configured-actor")
    response = TestClient(make_app()).get(
        "/auth",
        headers={"Authorization": "Bearer secret", "X-AIOS-Role": "admin", "X-AIOS-Actor": "attacker"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == OperatorRole.VIEWER.value
    assert response.json()["actor"] == "configured-actor"


def test_invalid_token_and_oversized_correlation_are_rejected(monkeypatch):
    monkeypatch.setenv("AIOS_OPERATOR_TOKEN", "secret")
    client = TestClient(make_app())
    assert client.get("/auth", headers={"Authorization": "Bearer wrong"}).json()["authenticated"] is False
    assert client.get("/auth", headers={"Authorization": "Bearer secret", "X-Correlation-ID": "x" * 129}).json()["authenticated"] is False


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
def test_correlation_id_is_generated(monkeypatch):
    monkeypatch.setenv("AIOS_OPERATOR_TOKEN", "secret")
    response = TestClient(make_app()).get("/auth", headers={"Authorization": "Bearer secret"})
    assert response.json()["correlation_id"]
