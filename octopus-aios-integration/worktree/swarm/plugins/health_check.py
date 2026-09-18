"""Health-check plugin: periodically probes all memory adapters.

Publishes :class:`AdapterHealthChanged` events when an adapter's status
transitions between ``healthy``, ``degraded`` and ``down``.

Enable via config.yaml::

    plugins:
      modules:
        - swarm.plugins.health_check

    health_check:
      interval: 60          # seconds between rounds
      degraded_threshold: 0.9   # availability < this → degraded
      down_threshold: 0.5       # availability < this → down
"""

from __future__ import annotations

import asyncio
import logging

from swarm.events.events import AdapterHealthChanged
from swarm.plugins.base import Plugin

logger = logging.getLogger(__name__)


def _classify(avail: float, *, degraded: float = 0.9, down: float = 0.5) -> str:
    if avail < down:
        return "down"
    if avail < degraded:
        return "degraded"
    return "healthy"


class HealthCheckPlugin(Plugin):
    name = "health_check"

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._previous: dict[str, str] = {}  # scheme → last status

    async def setup(self, container) -> None:
        cfg = container.cfg.get("health_check") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        self._interval = float(cfg.get("interval", 60))
        self._degraded = float(cfg.get("degraded_threshold", 0.9))
        self._down = float(cfg.get("down_threshold", 0.5))
        self._container = container
        if self._interval > 0:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self._check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("health_check round failed: %s", exc)

    async def _check(self) -> None:
        mp = getattr(self._container.agent, "memory_port", None)
        if mp is None:
            return
        metrics = getattr(mp, "metrics", None)
        if metrics is None:
            return

        for scheme in metrics.schemes():
            avail = metrics.availability(scheme)
            status = _classify(avail, degraded=self._degraded, down=self._down)
            prev = self._previous.get(scheme)
            if prev != status:
                self._previous[scheme] = status
                reason = f"availability={avail:.2%}"
                last_err = metrics.last_error.get(scheme, "")
                if last_err:
                    reason += f"; last_error={last_err[:80]}"
                await self._container.bus.publish(
                    AdapterHealthChanged(scheme=scheme, status=status, reason=reason)
                )
                if status != "healthy":
                    logger.warning(
                        "Adapter %s → %s (%s)", scheme, status, reason
                    )


def get_plugin() -> HealthCheckPlugin:
    return HealthCheckPlugin()


plugin = get_plugin()

__all__ = ["HealthCheckPlugin", "plugin"]
