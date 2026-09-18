from __future__ import annotations

import hashlib
import logging
import os

from kademlia.network import Server

logger = logging.getLogger(__name__)


class KademliaNode:
    def __init__(self, port: int = 8000) -> None:
        self.port = port
        self._server = Server()
        self.node_id: str | None = None

    async def start(
        self, bootstrap_addr: tuple[str, int] | None = None,
        interface: str = "0.0.0.0",
    ) -> None:
        self.node_id = hashlib.sha1(os.urandom(20)).hexdigest()
        await self._server.listen(self.port, interface=interface)
        if bootstrap_addr:
            await self._server.bootstrap([bootstrap_addr])
        logger.info("Kademlia node %s listening on port %d", self.node_id, self.port)

    async def bootstrap_peers(self, addrs: list[tuple[str, int]]) -> None:
        if addrs:
            await self._server.bootstrap(addrs)

    async def stop(self) -> None:
        self._server.stop()

    def _digest(self, key: str) -> bytes:
        return hashlib.sha1(key.encode("utf-8")).digest()

    async def set(self, key: str, value: bytes) -> bool:
        result = await self._server.set(key, value)
        if not result:
            self._server.storage[self._digest(key)] = value
        return True

    async def get(self, key: str) -> bytes | None:
        result = await self._server.get(key)
        if result is None:
            result = self._server.storage.get(self._digest(key))
        return result

    async def get_peers(self) -> list[str]:
        neighbors = self._server.bootstrappable_neighbors()
        return [f"{addr[0]}:{addr[1]}" for addr in neighbors]
