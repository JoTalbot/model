"""Fail-closed control-plane authentication configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlPlaneAuthConfig:
    token: str
    role: str
    actor: str

    @classmethod
    def from_env(cls) -> "ControlPlaneAuthConfig":
        token = os.getenv("AIOS_OPERATOR_TOKEN", "")
        role = os.getenv("AIOS_OPERATOR_ROLE", "")
        actor = os.getenv("AIOS_OPERATOR_ACTOR", "")
        if not token or not role or not actor:
            raise RuntimeError("AIOS operator authentication is not fully configured")
        if role not in {"viewer", "operator", "admin"}:
            raise RuntimeError(f"invalid AIOS_OPERATOR_ROLE: {role}")
        if len(token) < 16:
            raise RuntimeError("AIOS_OPERATOR_TOKEN must contain at least 16 characters")
        return cls(token=token, role=role, actor=actor)
