from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .carrier import CarrierRegistry


@dataclass
class PortableExecution:
    carrier_id: str
    runtime_kind: str
    accepted: bool
    payload: dict[str, Any]


class PortableRuntime:
    """Hardware-independent swarm execution substrate.

    Execution can migrate across:
    - VPS
    - browser runtimes
    - WASM
    - edge workers
    - containers
    - local devices
    """

    def __init__(self, carriers: CarrierRegistry) -> None:
        self.carriers = carriers

    def allocate(
        self,
        required_capabilities: list[str] | None = None,
    ) -> PortableExecution | None:
        matches = self.carriers.find(required_capabilities)

        if not matches:
            return None

        carrier = matches[0]

        return PortableExecution(
            carrier_id=carrier.carrier_id,
            runtime_kind=carrier.kind.value,
            accepted=True,
            payload={
                "capabilities": carrier.capabilities,
            },
        )
