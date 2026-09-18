from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any

logger = logging.getLogger(__name__)


class SwarmMDNS:
    """Optional LAN service advertisement and browse (requires ``zeroconf``)."""

    def __init__(
        self,
        service_type: str,
        refresh_interval: float,
        initial_browse: float,
    ) -> None:
        self.service_type = service_type
        self.refresh_interval = refresh_interval
        self.initial_browse = initial_browse
        self._peers: dict[str, dict[str, Any]] = {}
        self._az: Any = None
        self._listener: Any = None
        self._service_info: Any = None

    def peers_snapshot(self) -> list[dict[str, Any]]:
        rows = list(self._peers.values())
        rows.sort(key=lambda r: r.get("last_seen", 0.0), reverse=True)
        return rows

    async def start(
        self,
        *,
        host: str,
        ports: dict[str, int],
        node_id: str,
        instance_suffix: str,
        register: bool = True,
    ) -> None:
        from zeroconf import ServiceInfo, ServiceListener
        from zeroconf.asyncio import AsyncZeroconf

        self._az = AsyncZeroconf()
        kad_port = int(ports.get("kad", 8000))

        class _Listener(ServiceListener):
            def __init__(self, outer: SwarmMDNS) -> None:
                self._outer = outer

            def add_service(self, zc: Any, type_: str, name: str) -> None:
                self._outer._schedule_ingest(type_, name)

            def remove_service(self, zc: Any, type_: str, name: str) -> None:
                self._outer._peers.pop(name, None)

            def update_service(self, zc: Any, type_: str, name: str) -> None:
                self.add_service(zc, type_, name)

        if register:
            props = {
                b"node_id": node_id.encode("utf-8"),
                b"ports": json.dumps(ports).encode("utf-8"),
            }
            try:
                addr_bin = socket.inet_aton(host)
            except OSError:
                try:
                    addr_bin = socket.inet_aton(socket.gethostbyname(host))
                except OSError:
                    logger.warning("mDNS: could not resolve host %s; skipping register", host)
                    addr_bin = b"\x7f\x00\x00\x01"

            safe_suffix = instance_suffix.replace(" ", "-")[:60]
            name = f"{safe_suffix}.{self.service_type}"
            self._service_info = ServiceInfo(
                self.service_type,
                name,
                port=kad_port,
                properties=props,
                addresses=[addr_bin],
            )
            await self._az.async_register_service(self._service_info)

        self._listener = _Listener(self)
        await self._az.async_add_service_listener(self.service_type, self._listener)

        if self.initial_browse > 0:
            await asyncio.sleep(self.initial_browse)

    def _schedule_ingest(self, type_: str, name: str) -> None:
        if self._az is None:
            return

        async def _go() -> None:
            try:
                info = await self._az.async_get_service_info(type_, name, timeout=2000)
            except Exception as exc:
                logger.debug("mDNS get_service_info failed: %s", exc)
                return
            if info is None:
                return
            self._apply_service_info(info)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_go())

    def _apply_service_info(self, info: Any) -> None:
        now = time.time()
        props: dict[str, str] = {}
        raw = getattr(info, "properties", {}) or {}
        for k, v in raw.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            val = v.decode("utf-8") if isinstance(v, bytes) else str(v)
            props[key] = val

        port_map: dict[str, int] = {}
        if "ports" in props:
            try:
                port_map = {k: int(v) for k, v in json.loads(props["ports"]).items()}
            except (json.JSONDecodeError, TypeError, ValueError):
                port_map = {}

        kad = int(port_map.get("kad", getattr(info, "port", 0) or 0))
        kid = props.get("node_id") or props.get("id") or ""

        host = ""
        addrs = getattr(info, "addresses", None) or []
        if addrs:
            try:
                host = socket.inet_ntoa(addrs[0][:4])
            except OSError:
                host = str(addrs[0])

        if not host:
            server = getattr(info, "server", None) or ""
            host = server.rstrip(".")

        name = getattr(info, "name", "") or ""
        self._peers[name] = {
            "host": host,
            "kad": kad,
            "kid": kid,
            "last_seen": now,
        }

    async def stop(self) -> None:
        if self._az is None:
            return
        try:
            if self._listener is not None:
                await self._az.async_remove_service_listener(self._listener)
        except Exception as exc:
            logger.debug("mDNS remove listener: %s", exc)
        self._listener = None
        try:
            await self._az.async_close()
        except Exception as exc:
            logger.debug("mDNS async_close: %s", exc)
        self._az = None
        self._service_info = None
