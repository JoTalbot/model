"""RBAC dependencies for recovery control-plane operations."""

from fastapi import HTTPException, Request

from .security import OperatorRole, SecurityContext


def get_operator_context(request: Request) -> SecurityContext:
    context = getattr(request.state, "operator_context", None)
    if context is None:
        raise HTTPException(status_code=401, detail="operator authentication required")
    return context


def require_role(required: OperatorRole):
    def dependency(request: Request) -> SecurityContext:
        context = get_operator_context(request)
        if not context.role.allows(required):
            raise HTTPException(status_code=403, detail=f"role {required.value} required")
        return context
    return dependency
