import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.ref_parse import parse_ref
from swarm.memory.types import Artifact


@pytest.mark.asyncio
async def test_local_put_get(tmp_path):
    a = LocalScratchAdapter(root=tmp_path)
    art = Artifact(content=b"hello", mime="text/plain", tags=["note"])
    ref = await a.put(art)
    scheme, _ = parse_ref(ref)
    assert scheme == "file"
    out = await a.get(ref)
    assert out.content == b"hello"
    assert "note" in out.tags


@pytest.mark.asyncio
async def test_local_delete(tmp_path):
    a = LocalScratchAdapter(root=tmp_path)
    ref = await a.put(Artifact(content=b"x"))
    assert await a.exists(ref) is True
    assert await a.delete(ref) is True
    assert await a.exists(ref) is False


@pytest.mark.asyncio
async def test_worm_second_put_conflict(tmp_path):
    from swarm.memory.types import WormConflictError

    a = LocalScratchAdapter(root=tmp_path)
    ref = await a.put(
        Artifact(content=b"v1", tags=["dur:worm"]),
    )
    with pytest.raises(WormConflictError):
        await a.put(
            Artifact(
                content=b"v2",
                tags=["dur:worm"],
                attrs={"worm_base_ref": ref},
            )
        )


@pytest.mark.asyncio
async def test_worm_idempotent_same_bytes(tmp_path):
    a = LocalScratchAdapter(root=tmp_path)
    ref = await a.put(Artifact(content=b"same", tags=["dur:worm"]))
    ref2 = await a.put(
        Artifact(
            content=b"same",
            tags=["dur:worm"],
            attrs={"worm_base_ref": ref},
        )
    )
    assert ref2 == ref
