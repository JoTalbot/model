"""
swarm/network/gossip.py  (patched: межнодовая авторизация)
───────────────────────────────────────────────────────────
Изменения относительно оригинала
  • _handle_incoming → верифицирует auth-блок входящего UDP-пакета
  • _gossip_loop     → добавляет auth-блок к исходящим пакетам
  • Конструктор принимает опциональные signer / verifier
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import uuid
from collections import OrderedDict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import msgpack

from swarm.network.auth import AuthSigner, AuthVerifier

logger = logging.getLogger(__name__)


@dataclass
class GossipMessage:
    msg_type: str
    payload: dict
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


class GossipProtocol:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8001,
        on_message: Callable[[GossipMessage], Coroutine[Any, Any, None]] | None = None,
        interval: float = 5.0,
        fanout: int = 3,
        seen_capacity: int = 1000,
        *,
        bus=None,
        signer: AuthSigner | None = None,
        verifier: AuthVerifier | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._on_message   = on_message
        self.interval      = interval
        self.fanout        = fanout
        self.seen_capacity = seen_capacity
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._peers: list[tuple[str, int]] = []
        self._outbox: list[GossipMessage]  = []
        self._transport: asyncio.DatagramTransport | None = None
        self._gossip_task: asyncio.Task | None = None
        self._bus      = bus
        self._signer   = signer
        self._verifier = verifier

        # ── Счётчики ──
        self.total_received: int = 0
        self.total_sent: int     = 0
        self.total_rejected: int = 0   # новый: отклонённые пакеты

    def add_peer(self, host: str, port: int) -> None:
        if (host, port) not in self._peers:
            self._peers.append((host, port))

    def remove_peer(self, host: str, port: int) -> None:
        self._peers = [(h, p) for h, p in self._peers if (h, p) != (host, port)]

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._handle_incoming),
            local_addr=(self.host, self.port),
        )
        self._gossip_task = asyncio.create_task(self._gossip_loop())
        logger.info("Gossip listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._gossip_task:
            self._gossip_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gossip_task
        if self._transport:
            self._transport.close()

    async def _emit(self, event: object) -> None:
        if self._bus is not None:
            await self._bus.publish(event)

    async def inject(self, msg: GossipMessage) -> None:
        if msg.id in self._seen:
            return
        self._mark_seen(msg.id)
        if self._on_message:
            await self._on_message(msg)
        self._outbox.append(msg)

    # ── Приём ────────────────────────────────────────────────────────────────

    async def _handle_incoming(self, data: bytes, addr: tuple) -> None:
        try:
            raw = msgpack.unpackb(data, raw=False)

            # ── Верификация ──────────────────────────────────────────────────
            if self._verifier is not None:
                ok, reason = self._verifier.verify(raw)
                if not ok:
                    self.total_rejected += 1
                    logger.warning(
                        "Gossip auth failed from %s:%s — %s", addr[0], addr[1], reason
                    )
                    return

            msg = GossipMessage(
                msg_type=raw["msg_type"],
                payload=raw["payload"],
                id=raw["id"],
            )
            self.total_received += 1

            from swarm.events.events import GossipReceived
            from_addr = f"{addr[0]}:{addr[1]}" if addr else ""
            await self._emit(GossipReceived(
                msg_id=msg.id,
                msg_type=msg.msg_type,
                from_addr=from_addr,
            ))

            await self.inject(msg)
        except Exception as exc:
            logger.error("Gossip receive error: %s", exc)

    # ── Отправка ─────────────────────────────────────────────────────────────

    async def _gossip_loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            if not self._outbox or not self._peers:
                continue

            messages = list(self._outbox)
            self._outbox.clear()
            targets = random.sample(self._peers, min(self.fanout, len(self._peers)))
            sent_count = 0

            for msg in messages:
                envelope: dict[str, Any] = {
                    "msg_type": msg.msg_type,
                    "payload":  msg.payload,
                    "id":       msg.id,
                }

                # ── Подписываем пакет ────────────────────────────────────────
                if self._signer is not None:
                    envelope = self._signer.sign_envelope(envelope)

                data = msgpack.packb(envelope, use_bin_type=True)
                for host, port in targets:
                    if self._transport:
                        self._transport.sendto(data, (host, port))
                        sent_count += 1

            self.total_sent += sent_count

            if sent_count > 0:
                from swarm.events.events import GossipSent
                await self._emit(GossipSent(
                    msg_count=len(messages),
                    target_count=len(targets),
                ))

    def _mark_seen(self, msg_id: str) -> None:
        self._seen[msg_id] = None
        while len(self._seen) > self.seen_capacity:
            self._seen.popitem(last=False)

    def stats(self) -> dict:
        """Return a snapshot of gossip statistics."""
        return {
            "total_received": self.total_received,
            "total_sent":     self.total_sent,
            "total_rejected": self.total_rejected,
            "peers":          len(self._peers),
            "seen":           len(self._seen),
            "outbox":         len(self._outbox),
            "interval":       self.interval,
            "fanout":         self.fanout,
        }


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, handler: Callable) -> None:
        self._handler = handler

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        asyncio.ensure_future(self._handler(data, addr))
