"""HTTP transport for the operator recovery service."""

from collections.abc import Callable

from .recovery_api import RecoveryOperatorService

try:
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    APIRouter = None


if APIRouter is not None:
    class ResolveRequest(BaseModel):
        execution_id: str = Field(min_length=1)
        action: str = Field(min_length=1)
        reason: str | None = None

    class RetryRequest(BaseModel):
        execution_id: str = Field(min_length=1)
        reason: str | None = None


def build_recovery_router(service: RecoveryOperatorService, authorize_operator: Callable | None = None):
    if APIRouter is None:
        raise RuntimeError("FastAPI is required for the recovery HTTP transport")
    router = APIRouter(prefix="/recovery", tags=["operator-recovery"])

    def context(request: Request):
        if authorize_operator is None:
            raise HTTPException(status_code=403, detail="operator authorization is not configured")
        value = authorize_operator(request)
        if not value:
            raise HTTPException(status_code=403, detail="operator authorization required")
        return value

    @router.get("/queue")
    def queue(request: Request, action: str | None = None):
        context(request)
        return service.list(action=action)

    @router.get("/quarantine")
    def quarantine(request: Request):
        context(request)
        return service.list(action="quarantine")

    @router.get("/manual-review")
    def manual_review(request: Request):
        context(request)
        return service.list(action="manual_review")

    @router.post("/resolve")
    def resolve(payload: ResolveRequest, request: Request):
        operator = context(request)
        role = getattr(operator, "role", None)
        if getattr(role, "value", role) not in {"operator", "admin"}:
            raise HTTPException(status_code=403, detail="operator role required")
        try:
            return service.resolve(payload.execution_id, payload.action, actor=operator.actor, reason=payload.reason, correlation_id=operator.correlation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/retry")
    def retry(payload: RetryRequest, request: Request):
        operator = context(request)
        role = getattr(operator, "role", None)
        if getattr(role, "value", role) not in {"operator", "admin"}:
            raise HTTPException(status_code=403, detail="operator role required")
        try:
            return service.resolve(payload.execution_id, "retry", actor=operator.actor, reason=payload.reason, correlation_id=operator.correlation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
