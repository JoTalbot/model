import pytest

from swarm.memory.cloud_fallback import (
    cloud_auto_fallback_schemes,
    repository_save_with_store_fallback,
)


def test_cloud_auto_fallback_custom_order():
    cfg = {
        "memory_facade": {
            "cloud_paste": {
                "auto_fallback_order": ["catbox", "pasters"],
                "catbox": True,
                "pasters": True,
            }
        }
    }
    assert cloud_auto_fallback_schemes(cfg) == ["catbox", "pasters", "file"]


def test_cloud_auto_fallback_enabled_only():
    cfg = {
        "memory_facade": {
            "cloud_paste": {
                "pasters": True,
                "catbox": False,
            }
        }
    }
    assert cloud_auto_fallback_schemes(cfg) == ["pasters", "file"]


@pytest.mark.asyncio
async def test_repository_save_with_store_fallback_skips_failed():
    class FakeRepo:
        def __init__(self) -> None:
            self.tries: list[str] = []

        async def save(self, data, table, tags, attrs):
            self.tries.append(attrs.get("store"))
            if attrs.get("store") == "bad":
                raise RuntimeError("nope")
            return f"ref:{attrs['store']}:x"

    r = FakeRepo()
    ref, used = await repository_save_with_store_fallback(
        r,
        data={},
        table="t",
        tags=[],
        attrs_base={},
        schemes=["bad", "file"],
    )
    assert used == "file"
    assert ref == "ref:file:x"
    assert r.tries == ["bad", "file"]
