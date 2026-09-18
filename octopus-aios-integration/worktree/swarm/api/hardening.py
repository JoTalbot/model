"""Control-plane hardening kit (Wave 2, item 12).

Stdlib-only RBAC + fail-closed auth + CORS allowlist for the
:class:`swarm.api.control_plane.ControlPlaneServer` (which is based on
``http.server``, not FastAPI — so the FastAPI kit in
:mod:`swarm.tools_runtime.api_kit` cannot be wired directly; the patterns
here mirror it: roles, token map, audit).

Behaviour is **opt-in and backward compatible**::

    dashboard:
      require_auth: true        # default false → legacy fail-open
      localhost_bypass: true    # default true → 127.0.0.1 w/o auth OK
      tokens:                   # token → role map (min 16 chars each)
        "op-token-...": operator
        "ro-token-...": viewer
      cors_origins:             # default ["*"] → legacy behaviour
        - "https://dash.example.com"

Roles: ``viewer`` (GET) < ``operator`` (POST) < ``admin`` (reserved).
"""

from __future__ import annotations

import hmac
import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_LOG = logging.getLogger("swarm.api.hardening")

MIN_TOKEN_LEN = 16
_LOOPBACKS = {"127.0.0.1", "::1", "localhost"}


class OperatorRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

    def allows(self, minimum: OperatorRole) -> bool:
        rank = {OperatorRole.VIEWER: 0, OperatorRole.OPERATOR: 1, OperatorRole.ADMIN: 2}
        return rank[self] >= rank[minimum]


@dataclass(frozen=True)
class SecurityContext:
    actor: str
    role: OperatorRole
    client_ip: str


@dataclass
class AuthAttempt:
    ts: float
    client_ip: str
    reason: str
    role: str | None = None


class HardenedAuth:
    """Role-aware, optionally fail-closed auth for the control plane.

    Parameters
    ----------
    tokens:
        Mapping ``token → role`` (roles: viewer/operator/admin).
    require_auth:
        When True, requests without valid credentials are rejected even if
        no tokens are configured (fail-closed). Default False (legacy).
    localhost_bypass:
        When True (default), loopback clients are accepted as ``operator``
        without credentials. Set False for strict mode.
    legacy:
        Optional :class:`DashboardAuth` for HTTP Basic fallback (grants
        ``operator`` role on success).
    """

    def __init__(
        self,
        tokens: dict[str, str] | None = None,
        *,
        require_auth: bool = False,
        localhost_bypass: bool = True,
        legacy: Any = None,
        audit_size: int = 200,
    ) -> None:
        self._tokens: dict[str, OperatorRole] = {}
        for tok, role in (tokens or {}).items():
            if not isinstance(tok, str) or len(tok) < MIN_TOKEN_LEN:
                raise ValueError("dashboard token must be a string of >= 16 chars")
            try:
                self._tokens[tok] = OperatorRole(role)
            except ValueError:
                raise ValueError(f"invalid role for dashboard token: {role!r}") from None
        self._require_auth = require_auth
        self._localhost_bypass = localhost_bypass
        self._legacy = legacy
        self._audit: deque[AuthAttempt] = deque(maxlen=audit_size)

    @property
    def enabled(self) -> bool:
        return self._require_auth or bool(self._tokens) or (
            self._legacy is not None and self._legacy.enabled
        )

    def _log(self, ip: str, reason: str, role: str | None = None) -> None:
        self._audit.append(AuthAttempt(time.time(), ip, reason, role))
        if reason != "ok":
            _LOG.warning("control-plane auth %s from %s", reason, ip)

    def authorize(
        self, auth_header: str, client_ip: str, minimum_role: str | OperatorRole = "viewer"
    ) -> tuple[SecurityContext | None, str]:
        """Return ``(context, reason)``; context is None on rejection."""
        minimum = (
            minimum_role if isinstance(minimum_role, OperatorRole)
            else OperatorRole(minimum_role)
        )
        header = (auth_header or "").strip()

        # 1. Bearer token map
        if header.startswith("Bearer "):
            candidate = header[7:].strip()
            for tok, role in self._tokens.items():
                if candidate and hmac.compare_digest(candidate, tok):
                    if role.allows(minimum):
                        self._log(client_ip, "ok", role.value)
                        return SecurityContext("token", role, client_ip), "ok"
                    self._log(client_ip, "forbidden", role.value)
                    return None, "forbidden"
            # Unknown bearer token: fall through to legacy/basic, else reject.
            if self._legacy is not None and self._legacy.check_header(header):
                self._log(client_ip, "ok", "operator")
                if OperatorRole.OPERATOR.allows(minimum):
                    return SecurityContext("basic", OperatorRole.OPERATOR, client_ip), "ok"
                self._log(client_ip, "forbidden", "operator")
                return None, "forbidden"
            self._log(client_ip, "bad_token")
            return None, "bad_token"

        # 2. Basic auth via legacy checker
        if header.startswith("Basic ") and self._legacy is not None:
            if self._legacy.check_header(header):
                self._log(client_ip, "ok", "operator")
                if OperatorRole.OPERATOR.allows(minimum):
                    return SecurityContext("basic", OperatorRole.OPERATOR, client_ip), "ok"
                self._log(client_ip, "forbidden", "operator")
                return None, "forbidden"
            self._log(client_ip, "bad_basic")
            return None, "bad_basic"

        # 3. No credentials
        if self._localhost_bypass and client_ip in _LOOPBACKS and not self._require_auth:
            self._log(client_ip, "ok", "operator")
            if OperatorRole.OPERATOR.allows(minimum):
                return SecurityContext("localhost", OperatorRole.OPERATOR, client_ip), "ok"
            return None, "forbidden"
        if not self.enabled:
            # Legacy fail-open: nothing configured at all.
            return SecurityContext("open", OperatorRole.OPERATOR, client_ip), "open"
        self._log(client_ip, "fail_closed" if self._require_auth else "no_token")
        return None, "fail_closed" if self._require_auth else "no_token"

    def audit_stats(self) -> dict[str, Any]:
        reasons: dict[str, int] = {}
        for a in self._audit:
            reasons[a.reason] = reasons.get(a.reason, 0) + 1
        return {"attempts": len(self._audit), "reasons": reasons}


def cors_allow_origin(origin: str | None, allowlist: list[str] | None) -> str | None:
    """Resolve the ``Access-Control-Allow-Origin`` value.

    - ``["*"]`` (default) → ``"*"`` (legacy behaviour);
    - browser Origin in allowlist → echo it;
    - non-browser request (no Origin) → first allowlisted origin;
    - otherwise → None (omit header; browser blocks).
    """
    allowed = allowlist if allowlist else ["*"]
    if "*" in allowed:
        return "*"
    if origin and origin in allowed:
        return origin
    if not origin:
        return allowed[0]
    return None


def build_hardened_auth(cfg: dict, legacy: Any = None) -> HardenedAuth | None:
    """Build :class:`HardenedAuth` from ``config.yaml`` dashboard section.

    Returns None when no hardening keys are present (pure legacy mode).
    """
    dash = cfg.get("dashboard") or {}
    keys = ("tokens", "require_auth", "cors_origins", "localhost_bypass")
    if not any(k in dash for k in keys):
        return None
    return HardenedAuth(
        tokens=dash.get("tokens") or {},
        require_auth=bool(dash.get("require_auth", False)),
        localhost_bypass=bool(dash.get("localhost_bypass", True)),
        legacy=legacy,
    )


__all__ = [
    "MIN_TOKEN_LEN",
    "AuthAttempt",
    "HardenedAuth",
    "OperatorRole",
    "SecurityContext",
    "build_hardened_auth",
    "cors_allow_origin",
]
