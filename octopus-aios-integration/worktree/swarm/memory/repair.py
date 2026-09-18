from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ShardRepairSettings:
    """RPC pull settings for shard repair."""

    rpc_timeout_seconds: float = 8.0
    max_peers_per_shard: int = 32
    parallel_fetches: int = 3
    rpc_port_offset: int = 2000
    seeds: list[tuple[str, int]] = field(default_factory=list)  # (host, kad_port)
    local_rpc_host: str | None = None
    local_rpc_port: int | None = None


class ShardRepairService:
    """Repairs missing erasure shards via configured/neighbor RPC endpoints."""

    def __init__(self, kademlia, rpc_client, codec, settings: ShardRepairSettings) -> None:
        self.kademlia = kademlia
        self.rpc = rpc_client
        self.codec = codec
        self.settings = settings

    def replica_hints(self, node_id: str) -> list[dict]:
        if self.settings.local_rpc_host is None or self.settings.local_rpc_port is None:
            return []
        return [
            {
                "node_id": node_id,
                "rpc_host": self.settings.local_rpc_host,
                "rpc_port": int(self.settings.local_rpc_port),
            }
        ]

    async def repair_once(self, block_id: str, retrieve) -> bool:
        """Return True if ``retrieve(block_id)`` succeeds after repair attempts."""
        if await retrieve(block_id) is not None:
            return True

        meta = await self.codec.read_meta(block_id)
        if meta is None:
            return False

        shard_map = await self.codec.read_shards(block_id)
        missing = [
            i for i in range(self.codec.coder.total_shards) if i not in shard_map
        ]

        if not missing:
            return await retrieve(block_id) is not None

        sem = asyncio.Semaphore(max(1, self.settings.parallel_fetches))

        async def fetch_one(idx: int) -> tuple[int, bytes | None]:
            async with sem:
                b = await self._fetch_missing_shard(block_id, idx, meta)
                return idx, b

        pairs = await asyncio.gather(*[fetch_one(i) for i in missing])
        tentative: dict[int, bytes] = dict(shard_map)
        for idx, blob in pairs:
            if blob is not None:
                tentative[idx] = blob

        if len(tentative) < self.codec.coder.data_shards:
            logger.info(
                "repair_shards_once: block %s still incomplete after RPC pull "
                "(%d/%d shards)",
                block_id,
                len(tentative),
                self.codec.coder.data_shards,
            )
            return False

        try:
            content = self.codec.decode(tentative, meta["content_length"])
        except Exception as exc:
            logger.warning(
                "repair_shards_once: decode failed for block %s (discarding pull): %s",
                block_id,
                exc,
            )
            return False

        canonical = self.codec.encode(content)
        for idx in missing:
            await self.codec.write_shard(block_id, idx, canonical[idx])

        ok = await retrieve(block_id) is not None
        if not ok:
            logger.warning("repair_shards_once: retrieve failed after write for %s", block_id)
        return ok

    async def _neighbor_rpc_endpoints(self) -> list[tuple[str, int]]:
        gp = getattr(self.kademlia, "get_peers", None)
        if gp is None or not callable(gp):
            return []
        peers = await gp()
        out: list[tuple[str, int]] = []
        for line in peers:
            if not isinstance(line, str) or ":" not in line:
                continue
            host, _, sport = line.rpartition(":")
            try:
                kad_port = int(sport)
            except ValueError:
                continue
            out.append((host, kad_port + self.settings.rpc_port_offset))
        return out

    def _endpoint_queue(self, meta: dict) -> list[tuple[str, int]]:
        seen: set[tuple[str, int]] = set()
        ordered: list[tuple[str, int]] = []

        def add(host: str, port: int) -> None:
            t = (host, int(port))
            if t in seen:
                return
            seen.add(t)
            ordered.append(t)

        for hint in meta.get("replica_hints") or []:
            if not isinstance(hint, dict):
                continue
            h, p = hint.get("rpc_host"), hint.get("rpc_port")
            if isinstance(h, str) and isinstance(p, int):
                add(h, p)
        for host, kad_p in self.settings.seeds:
            add(host, kad_p + self.settings.rpc_port_offset)
        return ordered

    async def _full_endpoint_queue(self, meta: dict) -> list[tuple[str, int]]:
        q = self._endpoint_queue(meta)
        seen = set(q)
        for t in await self._neighbor_rpc_endpoints():
            if t not in seen:
                seen.add(t)
                q.append(t)
        return q

    async def _rpc_get_shard(
        self, host: str, rpc_port: int, block_id: str, shard_index: int
    ) -> bytes | None:
        try:
            res = await asyncio.wait_for(
                self.rpc.call(
                    host,
                    rpc_port,
                    "memory_shard_get",
                    {"block_id": block_id, "shard_index": shard_index},
                ),
                timeout=self.settings.rpc_timeout_seconds,
            )
        except Exception as exc:
            logger.debug(
                "memory_shard_get failed host=%s port=%s block=%s idx=%s: %s",
                host,
                rpc_port,
                block_id,
                shard_index,
                exc,
            )
            return None
        if not isinstance(res, dict) or not res.get("ok"):
            return None
        shard = res.get("shard")
        if isinstance(shard, bytes) and len(shard) > 0:
            return shard
        return None

    async def _fetch_missing_shard(
        self, block_id: str, shard_index: int, meta: dict
    ) -> bytes | None:
        endpoints = await self._full_endpoint_queue(meta)
        attempts = 0
        for host, rpc_port in endpoints:
            if attempts >= self.settings.max_peers_per_shard:
                break
            attempts += 1  # noqa: SIM113
            got = await self._rpc_get_shard(host, rpc_port, block_id, shard_index)
            if got is not None:
                return got
        return None
