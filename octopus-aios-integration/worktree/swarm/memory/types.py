from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    content: bytes | str
    mime: str = "application/octet-stream"
    tags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefMeta:
    ref: str
    scheme: str
    tags: list[str] = field(default_factory=list)
    block_type: str | None = None


@dataclass(frozen=True)
class Capabilities:
    schemes: frozenset[str]
    supports_search: bool
    supports_delete: bool
    supports_promote: bool


class RefNotFoundError(LookupError):
    pass


class MemoryAdapterError(RuntimeError):
    pass


class WormConflictError(MemoryAdapterError):
    pass


class PromotionError(MemoryAdapterError):
    pass
