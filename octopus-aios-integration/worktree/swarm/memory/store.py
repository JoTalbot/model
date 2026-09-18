from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from swarm.events.events import BlockRetrieved, BlockStored
from swarm.memory.encoding import MemoryCodec
from swarm.memory.erasure import ErasureCoder
from swarm.memory.repair import ShardRepairService, ShardRepairSettings
from swarm.memory.tag_index import TagIndex

logger = logging.getLogger(__name__)


@dataclass
class MemoryBlock:
    owner_id: str
    block_type: str
    content: bytes
    tags: list[str]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    ttl: int | None = None
    attrs: dict | None = None


class DistributedMemory:
    """Coordinator for metadata, erasure-coded shards, tags, and repair."""

    def __init__(
        self,
        kademlia,
        rpc_client,
        coder: ErasureCoder,
        node_id: str,
        *,
        shard_repair: ShardRepairSettings | None = None,
        bus=None,
    ) -> None:
        self._kademlia = kademlia
        self._rpc = rpc_client
        self._coder = coder
        self._node_id = node_id
        self._block_ids: list[str] = []
        self._repair = shard_repair or ShardRepairSettings()
        self._bus = bus
        self._codec = MemoryCodec(kademlia, coder)
        self._tag_index = TagIndex(kademlia)
        self._repair_service = ShardRepairService(
            kademlia,
            rpc_client,
            self._codec,
            self._repair,
        )

    async def repair_shards_once(self, block_id: str) -> bool:
        """Return True if ``retrieve(block_id)`` succeeds after repair attempts."""
        return await self._repair_service.repair_once(block_id, self.retrieve)

    async def scan_and_repair_round(self) -> int:
        """Run ``repair_shards_once`` for every block id seen on this node via ``store``."""
        n_ok = 0
        for bid in list(self._block_ids):
            if await self.repair_shards_once(bid):
                n_ok += 1
        return n_ok

    async def store(self, block: MemoryBlock) -> str:
        replica_hints = self._repair_service.replica_hints(self._node_id)
        await self._codec.write_meta(block, replica_hints)
        shards = await self._codec.write_shards(block.id, block.content)
        await self._tag_index.add(block.id, block.tags)

        logger.info("Stored block %s (%d bytes, %d shards)", block.id, len(block.content), len(shards))
        if block.id not in self._block_ids:
            self._block_ids.append(block.id)
        if self._bus is not None:
            await self._bus.publish(BlockStored(block.id))
        return block.id

    async def retrieve(self, block_id: str) -> MemoryBlock | None:
        meta = await self._codec.read_meta(block_id)
        if meta is None:
            return None

        shard_map = await self._codec.read_shards(block_id)
        if len(shard_map) < self._coder.data_shards:
            logger.error("Not enough shards to recover block %s", block_id)
            return None

        content = self._codec.decode(shard_map, meta["content_length"])
        if self._bus is not None:
            await self._bus.publish(BlockRetrieved(block_id))
        return MemoryBlock(
            id=meta["id"],
            owner_id=meta["owner_id"],
            block_type=meta["block_type"],
            content=content,
            tags=meta["tags"],
            timestamp=meta["timestamp"],
            ttl=meta["ttl"],
            attrs=meta.get("attrs") or None,
        )

    async def search(
        self, tags: list[str], owner: str | None = None
    ) -> list[MemoryBlock]:
        block_ids = await self._tag_index.ids_for(tags)
        results = []
        for bid in block_ids:
            block = await self.retrieve(bid)
            if block and (owner is None or block.owner_id == owner):
                results.append(block)
        return results

    async def delete(self, block_id: str) -> bool:
        meta = await self._codec.read_meta(block_id)
        if meta is None:
            return False

        await self._tag_index.remove(block_id, meta.get("tags", []))
        await self._codec.delete_shards(block_id)
        await self._codec.delete_meta(block_id)
        return True
