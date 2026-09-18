from __future__ import annotations

from swarm.memory.ref_parse import make_ref, parse_ref
from swarm.memory.store import MemoryBlock
from swarm.memory.types import Artifact, Capabilities, RefMeta, RefNotFoundError


class DhtErasureAdapter:
    """Wraps `DistributedMemory` with `ref:swarm:<block_id>` addressing."""

    scheme: str = "swarm"

    def __init__(
        self,
        distributed_memory,
        *,
        default_block_type: str = "knowledge",
        owner_id: str,
    ) -> None:
        self._dm = distributed_memory
        self._default_block_type = default_block_type
        self._owner_id = owner_id

    def _artifact_content_bytes(self, artifact: Artifact) -> bytes:
        if isinstance(artifact.content, str):
            return artifact.content.encode("utf-8")
        return artifact.content

    async def put(self, artifact: Artifact) -> str:
        content = self._artifact_content_bytes(artifact)
        block = MemoryBlock(
            owner_id=self._owner_id,
            block_type=artifact.attrs.get("block_type") or self._default_block_type,
            content=content,
            tags=artifact.tags,
            attrs=artifact.attrs or None,
        )
        block_id = await self._dm.store(block)
        return make_ref("swarm", block_id)

    async def get(self, ref: str) -> Artifact:
        scheme, block_id = parse_ref(ref)
        assert scheme == "swarm"
        block = await self._dm.retrieve(block_id)
        if block is None:
            raise RefNotFoundError(ref)
        return Artifact(
            content=block.content,
            tags=block.tags,
            mime="application/octet-stream",
            provenance={},
            attrs=block.attrs or {},
        )

    async def exists(self, ref: str) -> bool:
        scheme, block_id = parse_ref(ref)
        if scheme != "swarm":
            return False
        return await self._dm.retrieve(block_id) is not None

    async def delete(self, ref: str) -> bool:
        scheme, block_id = parse_ref(ref)
        if scheme != "swarm":
            return False
        return await self._dm.delete(block_id)

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        blocks = await self._dm.search(tags, owner)
        return [
            RefMeta(
                ref=make_ref("swarm", block.id),
                scheme="swarm",
                tags=block.tags,
                block_type=block.block_type,
            )
            for block in blocks
        ]

    def capabilities(self) -> Capabilities:
        return Capabilities(
            schemes=frozenset({"swarm"}),
            supports_search=True,
            supports_delete=True,
            supports_promote=False,
        )
