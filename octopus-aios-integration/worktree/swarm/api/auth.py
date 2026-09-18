"""Lightweight authentication for the control-plane API.

Supports:
- Bearer token (``Authorization: Bearer <token>``)
- HTTP Basic auth (``Authorization: Basic <b64(user:pass)>``)
- No auth (when neither token nor password is configured — localhost only)

Config (``config.yaml``):

.. code-block:: yaml

    dashboard:
      token: "my-secret"
      # or basic auth:
      # username: admin
      # password: changeme
"""

from __future__ import annotations

import base64
import hmac
import time
from collections import defaultdict


class DashboardAuth:
    """Check incoming requests against configured credentials."""

    def __init__(self, cfg: dict) -> None:
        dash = cfg.get("dashboard") or {}
        self._token: str | None = dash.get("token")
        self._username: str = dash.get("username", "admin")
        self._password: str | None = dash.get("password")

    @property
    def enabled(self) -> bool:
        return bool(self._token or self._password)

    def check_header(self, auth_header: str) -> bool:
        """Return True if the Authorization header is valid."""
        if not self.enabled:
            return True

        if not auth_header:
            return False

        if auth_header.startswith("Bearer ") and self._token:
            candidate = auth_header[7:].strip()
            return hmac.compare_digest(candidate, self._token)

        if auth_header.startswith("Basic ") and self._password:
            try:
                decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                return (
                    hmac.compare_digest(user, self._username)
                    and hmac.compare_digest(pwd, self._password)
                )
            except Exception:
                return False

        return False


class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Not thread-safe in the strictest sense, but good enough for a
    stdlib ``ThreadingHTTPServer`` where handler threads are short-lived
    and the window granularity is seconds.
    """

    def __init__(
        self, max_requests: int = 200, window_seconds: int = 60
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: defaultdict[str, list[float]] = defaultdict(list)

    def allow(self, client_ip: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        bucket = self._buckets[client_ip]
        # Prune old entries (amortised O(1) most of the time).
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= self.max_requests:
            return False
        bucket.append(now)
        return True


__all__ = ["DashboardAuth", "RateLimiter"]
