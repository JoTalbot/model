from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class CarrierKind(str, Enum):
    VPS = "vps"
    CONTAINER = "container"
    BROWSER = "browser"
    EDGE = "edge"
    LOCAL = "local"
    WASM = "wasm"
    UNKNOWN = "unknown"


@dataclass
class RuntimeCarrier:
    """Temporary hardware/software host for swarm execution.

    A carrier is not identity. It is only a disposable body for execution.
    """

    carrier_id: str
    kind: CarrierKind = CarrierKind.UNKNOWN
    capabilities: dict[str, Any] = field(default_factory=dict)
    first_seen: float = field(default_factory=time)
    last_seen: float = field(default_factory=time)

    def touch(self) -> None:
        self.last_seen = time()

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability, False))


class CarrierRegistry:
    """Registry of available temporary execution bodies."""

    def __init__(self) -> None:
        self.carriers: dict[str, RuntimeCarrier] = {}

    def register(
        self,
        carrier_id: str,
        kind: CarrierKind = CarrierKind.UNKNOWN,
        capabilities: dict[str, Any] | None = None,
    ) -> RuntimeCarrier:
        carrier = self.carriers.get(carrier_id)
        if carrier is None:
            carrier = RuntimeCarrier(
                carrier_id=carrier_id,
                kind=kind,
                capabilities=capabilities or {},
            )
            self.carriers[carrier_id] = carrier
        else:
            carrier.kind = kind
            carrier.capabilities.update(capabilities or {})
            carrier.touch()
        return carrier

    def find(self, required: list[str] | None = None) -> list[RuntimeCarrier]:
        required = required or []
        return [
            carrier
            for carrier in self.carriers.values()
            if all(carrier.supports(capability) for capability in required)
        ]
