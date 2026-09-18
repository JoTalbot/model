from __future__ import annotations

import msgpack


class TagIndex:
    """Maintains the tag -> block id index in Kademlia."""

    def __init__(self, kademlia) -> None:
        self.kademlia = kademlia

    async def add(self, block_id: str, tags: list[str]) -> None:
        for tag in tags:
            tag_key = f"tag:{tag}"
            existing = await self.kademlia.get(tag_key)
            if existing:
                id_list = msgpack.unpackb(existing, raw=False)
            else:
                id_list = []
            if block_id not in id_list:
                id_list.append(block_id)
            await self.kademlia.set(tag_key, msgpack.packb(id_list, use_bin_type=True))

    async def ids_for(self, tags: list[str]) -> set[str]:
        block_ids: set[str] = set()
        for tag in tags:
            raw = await self.kademlia.get(f"tag:{tag}")
            if raw:
                ids = msgpack.unpackb(raw, raw=False)
                block_ids.update(ids)
        return block_ids

    async def remove(self, block_id: str, tags: list[str]) -> None:
        for tag in tags:
            tag_key = f"tag:{tag}"
            raw = await self.kademlia.get(tag_key)
            if raw:
                id_list = msgpack.unpackb(raw, raw=False)
                id_list = [bid for bid in id_list if bid != block_id]
                await self.kademlia.set(tag_key, msgpack.packb(id_list, use_bin_type=True))
