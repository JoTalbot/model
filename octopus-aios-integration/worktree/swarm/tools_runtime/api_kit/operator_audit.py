"""Operator audit control-plane endpoints."""

from fastapi import APIRouter, Depends, Request

from .security import OperatorRole, require_role


def build_operator_audit_router(service, authorize_operator=None):
    router = APIRouter(prefix="/operator", tags=["operator"])

    def guard(request: Request):
        return require_role(request, OperatorRole.VIEWER)

    @router.get("/audit", dependencies=[Depends(guard)])
    def audit():
        return service.audit_events()

    return router
