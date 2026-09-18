"""Retry-with-backoff helpers for memory adapters.

Public cloud paste-bins (catbox, telegraph, transfer.sh, ...) intermittently
return 5xx, 502s, or just time out under load.  A single missed request
should not kill an upload that has 13 other backends ready to try.

This module provides:

* :class:`RetryPolicy` — declarative knobs (max_attempts, base_delay,
  max_delay, backoff factor, optional jitter, optional list of "should-
  retry" exception predicates).
* :func:`compute_delay` — pure helper that produces the next delay given
  attempt number and a policy.
* :func:`is_transient_error` — default predicate flagging
  ``httpx.HTTPError`` / ``MemoryAdapterError`` / OSError as retryable.
* :func:`retry_call` — async runner that loops over a coroutine factory.
* :class:`RetryingAdapter` — thin adapter wrapper that retries ``put`` and
  ``get`` (and ``exists``) according to a policy.

Design notes
------------
* The wrapper is **transparent**: scheme + capabilities pass through, so a
  composite port treats a retrying adapter exactly like the bare one.
* Retries do NOT happen on ``RefNotFoundError`` (a known-good 404 is not
  transient; failing fast keeps Dropbox.download moving to the next mirror).
* Exponential backoff with full jitter (sleep = random(0, capped_delay)),
  which empirically reduces thundering-herd under contention.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    RefMeta,
    RefNotFoundError,
)

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def is_transient_error(exc: BaseException) -> bool:
    """Default 'should retry' predicate.

    Treats common transient failures as retryable; leaves logical errors
    (RefNotFoundError, ValueError, etc) alone.
    """
    if isinstance(exc, RefNotFoundError):
        return False
    if isinstance(exc, MemoryAdapterError):
        msg = str(exc).lower()
        # 4xx (except 408/429) are non-retryable client mistakes.
        for code in ("400", "401", "403", "404", "405", "410", "413", "415"):
            if f" http {code}" in msg or f"http {code}:" in msg or f"http {code} " in msg:
                return False
        return True
    if isinstance(exc, httpx.HTTPError):
        return True
    if isinstance(exc, asyncio.TimeoutError):
        return True
    return bool(isinstance(exc, OSError))


@dataclass(frozen=True)
class RetryPolicy:
    """Retry knobs.  Defaults: 3 attempts, 0.25–8 s exponential w/ jitter."""

    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 8.0
    backoff: float = 2.0
    jitter: bool = True
    should_retry: Callable[[BaseException], bool] = field(default=is_transient_error)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must be non-negative")
        if self.backoff < 1.0:
            raise ValueError("backoff factor must be >= 1.0")


def compute_delay(attempt: int, policy: RetryPolicy) -> float:
    """Return seconds to sleep BEFORE retry ``attempt`` (1-indexed).

    ``attempt=1`` returns 0 (the first try has no preceding delay).
    Subsequent attempts grow exponentially, capped at ``max_delay`` and
    optionally jittered.
    """
    if attempt <= 1:
        return 0.0
    raw = policy.base_delay * (policy.backoff ** (attempt - 2))
    capped = min(policy.max_delay, raw)
    if policy.jitter:
        return random.uniform(0, capped)
    return capped


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def retry_call(
    factory: Callable[[], Awaitable[Any]],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> Any:
    """Run ``factory()`` with retries.

    ``factory`` MUST be a zero-arg callable returning a fresh awaitable on
    every call.  ``sleep`` is hookable for tests so they don't wait in
    wall-clock.
    """
    if sleep is None:
        sleep = asyncio.sleep
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        delay = compute_delay(attempt, policy)
        if delay > 0:
            await sleep(delay)
        try:
            return await factory()
        except BaseException as exc:
            last_exc = exc
            if not policy.should_retry(exc) or attempt == policy.max_attempts:
                raise
    assert last_exc is not None  # for mypy
    raise last_exc


# ---------------------------------------------------------------------------
# RetryingAdapter
# ---------------------------------------------------------------------------

class RetryingAdapter:
    """Wrap any memory adapter so put/get/exists auto-retry transient errors.

    Search and delete pass through untouched: deletes are usually fire-and-
    forget on anonymous pastebins (they all return False anyway), and
    search results don't benefit from retries.
    """

    def __init__(self, inner, policy: RetryPolicy | None = None) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self.scheme = getattr(inner, "scheme", "unknown")

    @property
    def inner(self):
        return self._inner

    async def put(self, artifact: Artifact) -> str:
        return await retry_call(lambda: self._inner.put(artifact), self._policy)

    async def get(self, ref: str) -> Artifact:
        return await retry_call(lambda: self._inner.get(ref), self._policy)

    async def exists(self, ref: str) -> bool:
        try:
            return await retry_call(lambda: self._inner.exists(ref), self._policy)
        except RefNotFoundError:
            return False

    async def delete(self, ref: str) -> bool:
        return await self._inner.delete(ref)

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        return await self._inner.search(tags, owner)

    def capabilities(self) -> Capabilities:
        return self._inner.capabilities()


def wrap_adapters_with_retry(
    adapters: dict[str, Any],
    *,
    policy: RetryPolicy | None = None,
    only: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a new dict with every (selected) adapter wrapped in retries.

    ``only`` restricts wrapping to a subset of scheme names.  ``file`` and
    ``swarm`` are NOT auto-wrapped: local writes don't fail transiently and
    the DHT has its own resilience layer.
    """
    skip = {"file", "swarm"}
    result: dict[str, Any] = {}
    for name, adapter in adapters.items():
        if name in skip:
            result[name] = adapter
            continue
        if only is not None and name not in only:
            result[name] = adapter
            continue
        result[name] = RetryingAdapter(adapter, policy=policy)
    return result
