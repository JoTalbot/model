"""FastAPI application factory for AIOS control-plane endpoints."""

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request

from swarm.tools_runtime.recovery_api import RecoveryOperatorService
from swarm.tools_runtime.recovery_http import build_recovery_router

from .auth_config import ControlPlaneAuthConfig
from .security import SecurityContext, authenticate


def create_app(*, recovery_service: RecoveryOperatorService | None = None,
               operator_validator: Callable[[Request], SecurityContext | None] | None = None,
               readiness_check: Callable[[], bool] | None = None,
               auth_config: ControlPlaneAuthConfig | None = None):
    app = FastAPI(title="AIOS API", version="vNext")
    service = recovery_service or RecoveryOperatorService()
    config = auth_config
    if config is None and operator_validator is None:
        config = ControlPlaneAuthConfig.from_env()

    def authorize(request: Request):
        context = operator_validator(request) if operator_validator is not None else authenticate(request, config)
        if not context:
            raise HTTPException(status_code=403, detail="operator authorization required")
        request.state.operator_context = context
        return context

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "system": "AIOS"}

    @app.get("/ready", tags=["system"])
    async def ready():
        if readiness_check is not None and not readiness_check():
            raise HTTPException(status_code=503, detail="AIOS dependencies are not ready")
        return {"status": "ready", "system": "AIOS"}

    app.include_router(build_recovery_router(service, authorize_operator=authorize))
    return app
