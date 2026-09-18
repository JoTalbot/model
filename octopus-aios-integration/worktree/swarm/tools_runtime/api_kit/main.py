"""Uvicorn entrypoint for the AIOS control plane."""

from .app import create_app
from .security import authenticate

app = create_app(operator_validator=authenticate)
