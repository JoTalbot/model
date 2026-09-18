from __future__ import annotations

import msgpack

from swarm.memory.erasure import ErasureCoder


class MemoryCodec:
    """Handles metadata serialization and erasure-coded shard IO."""

    def __init__(self, kademlia, coder: ErasureCoder) -> None:
        self.kademlia = kademlia
        self.coder = coder

    def pack_meta(self, block, replica_hints: list[dict]) -> bytes:
        return msgpack.packb(
            {
                "id": block.id,
                "owner_id": block.owner_id,
                "block_type": block.block_type,
                "timestamp": block.timestamp,
                "ttl": block.ttl,
                "tags": block.tags,
                "attrs": block.attrs or {},
                "content_length": len(block.content),
                "replica_hints": replica_hints,
            },
            use_bin_type=True,
        )

    def unpack_meta(self, raw: bytes) -> dict:
        return msgpack.unpackb(raw, raw=False)

    async def write_meta(self, block, replica_hints: list[dict]) -> None:
        await self.kademlia.set(f"meta:{block.id}", self.pack_meta(block, replica_hints))

    async def read_meta(self, block_id: str) -> dict | None:
        meta_raw = await self.kademlia.get(f"meta:{block_id}")
        if meta_raw is None:
            return None
        return self.unpack_meta(meta_raw)

    async def delete_meta(self, block_id: str) -> None:
        await self.kademlia.set(f"meta:{block_id}", None)

    async def write_shards(self, block_id: str, content: bytes) -> list[bytes]:
        shards = self.coder.encode(content)
        for i, shard in enumerate(shards):
            await self.write_shard(block_id, i, shard)
        return shards

    async def write_shard(self, block_id: str, shard_index: int, shard: bytes | None) -> None:
        await self.kademlia.set(f"shard:{block_id}:{shard_index}", shard)

    async def read_shards(self, block_id: str) -> dict[int, bytes]:
        shard_map: dict[int, bytes] = {}
        for i in range(self.coder.total_shards):
            shard_data = await self.kademlia.get(f"shard:{block_id}:{i}")
            if shard_data is not None:
                shard_map[i] = shard_data
        return shard_map

    async def delete_shards(self, block_id: str) -> None:
        for i in range(self.coder.total_shards):
            await self.write_shard(block_id, i, None)

    def decode(self, shard_map: dict[int, bytes], content_length: int) -> bytes:
        return self.coder.decode(shard_map, content_length)

    def encode(self, content: bytes) -> list[bytes]:
        return self.coder.encode(content)
