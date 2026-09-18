from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class APIKey:
    key: str
    requests_made: int = 0
    last_error: float | None = None
    cooldown_until: float | None = None


class KeyPool:
    def __init__(self, keys: list[APIKey]) -> None:
        if not keys:
            raise ValueError("At least one API key required")
        self.keys = keys
        self._index = 0

    def get_key(self) -> APIKey:
        now = time.time()
        available = [
            k for k in self.keys
            if k.cooldown_until is None or k.cooldown_until <= now
        ]
        if not available:
            raise RuntimeError("No available API keys")
        key = available[self._index % len(available)]
        self._index = (self._index + 1) % len(available)
        return key

    def mark_failed(self, key: APIKey, cooldown_seconds: int = 60) -> None:
        now = time.time()
        key.last_error = now
        key.cooldown_until = now + cooldown_seconds

    def mark_success(self, key: APIKey) -> None:
        key.last_error = None
        key.cooldown_until = None
        key.requests_made += 1
