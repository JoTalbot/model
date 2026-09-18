"""Wave 2 item 12: control-plane hardening kit tests."""

import threading
from http.server import ThreadingHTTPServer

import pytest

from swarm.api.auth import DashboardAuth
from swarm.api.hardening import (
    HardenedAuth,
    OperatorRole,
    build_hardened_auth,
    cors_allow_origin,
)

OP_TOKEN = "op-token-0123456789abcdef"
RO_TOKEN = "ro-token-0123456789abcdef"


def _auth(**kw):
    kw.setdefault("tokens", {OP_TOKEN: "operator", RO_TOKEN: "viewer"})
    return HardenedAuth(**kw)


# --- roles ---


def test_role_ranking():
    assert OperatorRole.ADMIN.allows(OperatorRole.OPERATOR)
    assert OperatorRole.OPERATOR.allows(OperatorRole.VIEWER)
    assert not OperatorRole.VIEWER.allows(OperatorRole.OPERATOR)
    assert OperatorRole.VIEWER.allows(OperatorRole.VIEWER)


def test_short_token_rejected():
    with pytest.raises(ValueError):
        HardenedAuth(tokens={"short": "viewer"})


def test_bad_role_rejected():
    with pytest.raises(ValueError):
        HardenedAuth(tokens={"long-enough-token-123": "superuser"})


# --- bearer map ---


def test_bearer_ok_and_forbidden():
    h = _auth()
    ctx, reason = h.authorize(f"Bearer {OP_TOKEN}", "10.0.0.5", minimum_role="operator")
    assert reason == "ok" and ctx.role == OperatorRole.OPERATOR
    ctx, reason = h.authorize(f"Bearer {RO_TOKEN}", "10.0.0.5", minimum_role="operator")
    assert ctx is None and reason == "forbidden"
    ctx, reason = h.authorize(f"Bearer {RO_TOKEN}", "10.0.0.5", minimum_role="viewer")
    assert reason == "ok"


def test_bearer_unknown_token():
    h = _auth()
    ctx, reason = h.authorize("Bearer nope-not-a-real-token-000", "10.0.0.5")
    assert ctx is None and reason == "bad_token"


# --- fail-closed / bypass ---


def test_fail_closed_without_creds():
    h = _auth(require_auth=True, localhost_bypass=False)
    ctx, reason = h.authorize("", "10.0.0.5")
    assert ctx is None and reason == "fail_closed"


def test_localhost_bypass_default():
    h = _auth()
    ctx, reason = h.authorize("", "127.0.0.1")
    assert reason == "ok" and ctx.actor == "localhost"


def test_legacy_fail_open_when_nothing_configured():
    h = HardenedAuth()
    ctx, reason = h.authorize("", "10.0.0.5")
    assert reason == "open" and ctx is not None


def test_basic_delegation_to_legacy():
    legacy = DashboardAuth({"dashboard": {"username": "admin", "password": "s3cret-pw"}})
    h = HardenedAuth(tokens={}, legacy=legacy)
    import base64

    basic = base64.b64encode(b"admin:s3cret-pw").decode()
    ctx, reason = h.authorize(f"Basic {basic}", "10.0.0.5")
    assert reason == "ok" and ctx.role == OperatorRole.OPERATOR
    ctx, reason = h.authorize("Basic YWRtaW46d3Jvbmc=", "10.0.0.5")
    assert ctx is None and reason == "bad_basic"


def test_audit_stats_counts_rejections():
    h = _auth()
    h.authorize("Bearer bad-token-00000000000000", "10.0.0.9")
    h.authorize(f"Bearer {RO_TOKEN}", "10.0.0.9", minimum_role="operator")
    stats = h.audit_stats()
    assert stats["reasons"].get("bad_token") == 1
    assert stats["reasons"].get("forbidden") == 1


# --- CORS ---


def test_cors_legacy_star():
    assert cors_allow_origin(None, ["*"]) == "*"
    assert cors_allow_origin("https://x.io", None) == "*"


def test_cors_allowlist():
    allowed = ["https://dash.example.com"]
    assert cors_allow_origin("https://dash.example.com", allowed) == "https://dash.example.com"
    assert cors_allow_origin("https://evil.io", allowed) is None
    assert cors_allow_origin(None, allowed) == "https://dash.example.com"


# --- config builder ---


def test_build_returns_none_in_legacy_mode():
    assert build_hardened_auth({}) is None
    assert build_hardened_auth({"dashboard": {"token": "x"}}) is None


def test_build_from_config():
    h = build_hardened_auth({"dashboard": {"tokens": {OP_TOKEN: "operator"}, "require_auth": True}})
    assert isinstance(h, HardenedAuth)
    _, reason = h.authorize(f"Bearer {OP_TOKEN}", "10.0.0.5")
    assert reason == "ok"


# --- socket integration: hardened server rejects/accepts ---


def _run_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_control_plane_hardened_over_http():
    from swarm.api.control_plane import _ControlPlaneHandler

    class StubMetrics:
        def schemes(self):
            return []

    class Bound(_ControlPlaneHandler):
        pass

    Bound._metrics = StubMetrics()
    Bound._container = None
    Bound._collector = None
    Bound._sse_bridge = None
    Bound._audit_provider_box = [None]
    Bound._auth = None
    Bound._rate_limiter = None
    Bound._hardened = _auth(require_auth=True, localhost_bypass=False)
    Bound._cors_origins = ["*"]

    server = _run_server(Bound)
    try:
        import urllib.error
        import urllib.request

        base = f"http://127.0.0.1:{server.server_address[1]}"
        # No token → 401
        try:
            urllib.request.urlopen(base + "/api/v1/node/info", timeout=5)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        # Viewer token on GET → 200
        req = urllib.request.Request(
            base + "/api/v1/node/info", headers={"Authorization": f"Bearer {RO_TOKEN}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
        # Viewer token on POST → 403 (operator required)
        req = urllib.request.Request(
            base + "/api/v1/tasks",
            data=b"{}",
            headers={"Authorization": f"Bearer {RO_TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected 403")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    finally:
        server.shutdown()
        server.server_close()
