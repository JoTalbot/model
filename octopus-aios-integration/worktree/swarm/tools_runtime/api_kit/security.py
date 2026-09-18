"""Canonical control-plane authentication context and RBAC."""

import hmac
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from fastapi import HTTPException, Request

from .auth_config import ControlPlaneAuthConfig


class OperatorRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

    def allows(self, minimum: "OperatorRole") -> bool:
        rank = {OperatorRole.VIEWER: 0, OperatorRole.OPERATOR: 1, OperatorRole.ADMIN: 2}
        return rank[self] >= rank[minimum]


@dataclass(frozen=True)
class SecurityContext:
    actor: str
    role: OperatorRole
    correlation_id: str


def authenticate(request: Request, config: ControlPlaneAuthConfig | None = None) -> SecurityContext | None:
    """Authenticate against validated server-side configuration only."""
    if config is None:
        try:
            config = ControlPlaneAuthConfig.from_env()
        except RuntimeError:
            return None
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    supplied_token = authorization[7:]
    if not supplied_token or not hmac.compare_digest(supplied_token, config.token):
        return None
    correlation_id = request.headers.get("x-correlation-id") or str(uuid4())
    if len(correlation_id) > 128:
        return None
    return SecurityContext(actor=config.actor, role=OperatorRole(config.role), correlation_id=correlation_id)


def require_role(request: Request, minimum: OperatorRole) -> SecurityContext:
    context = authenticate(request)
    if context is None:
        raise HTTPException(status_code=403, detail="operator authorization required")
    if not context.role.allows(minimum):
        raise HTTPException(status_code=403, detail=f"role {minimum.value} required")
    request.state.operator_context = context
    return context
