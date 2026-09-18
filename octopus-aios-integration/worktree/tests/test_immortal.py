"""Тесты для swarm.memory.immortal — cold storage (IPFS/Arweave)."""

import pytest

from swarm.memory.immortal import (
    ArchiveRecord,
    ArweaveProvider,
    EncryptedStorage,
    ImmortalMemoryManager,
    IPFSProvider,
)

# ── IPFSProvider (simulated) ──────────────────────────────────────────────


class TestIPFSProvider:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        ipfs = IPFSProvider(simulate=True)
        content = b"Hello IPFS World"
        cid = await ipfs.store(content, {"tag": "test"})
        assert cid.startswith("bafy")

        retrieved = await ipfs.retrieve(cid)
        assert retrieved == content

    @pytest.mark.asyncio
    async def test_exists(self):
        ipfs = IPFSProvider(simulate=True)
        content = b"exists test"
        cid = await ipfs.store(content, {})

        assert await ipfs.exists(cid) is True
        assert await ipfs.exists("bafy_nonexistent") is False

    @pytest.mark.asyncio
    async def test_retrieve_missing(self):
        ipfs = IPFSProvider(simulate=True)
        result = await ipfs.retrieve("missing_cid")
        assert result == b""

    @pytest.mark.asyncio
    async def test_store_deterministic(self):
        """Одинаковый контент → одинаковый CID."""
        ipfs = IPFSProvider(simulate=True)
        cid1 = await ipfs.store(b"same", {})
        cid2 = await ipfs.store(b"same", {})
        assert cid1 == cid2

    @pytest.mark.asyncio
    async def test_different_content_different_cid(self):
        ipfs = IPFSProvider(simulate=True)
        cid1 = await ipfs.store(b"aaa", {})
        cid2 = await ipfs.store(b"bbb", {})
        assert cid1 != cid2


# ── ArweaveProvider (simulated) ───────────────────────────────────────────


class TestArweaveProvider:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        ar = ArweaveProvider(simulate=True)
        content = b"Hello Arweave"
        tx_id = await ar.store(content, {"importance": "0.9"})
        assert len(tx_id) == 43

        retrieved = await ar.retrieve(tx_id)
        assert retrieved == content

    @pytest.mark.asyncio
    async def test_exists(self):
        ar = ArweaveProvider(simulate=True)
        tx_id = await ar.store(b"data", {})
        assert await ar.exists(tx_id) is True
        assert await ar.exists("nonexistent_tx") is False

    @pytest.mark.asyncio
    async def test_retrieve_with_prefix(self):
        ar = ArweaveProvider(simulate=True)
        tx_id = await ar.store(b"prefixed", {})
        # retrieve с префиксом ar:
        retrieved = await ar.retrieve(f"ar:{tx_id}")
        assert retrieved == b"prefixed"

    @pytest.mark.asyncio
    async def test_retrieve_missing(self):
        ar = ArweaveProvider(simulate=True)
        result = await ar.retrieve("missing")
        assert result == b""


# ── EncryptedStorage ──────────────────────────────────────────────────────


class TestEncryptedStorage:
    @pytest.mark.asyncio
    async def test_encrypt_decrypt_roundtrip(self):
        inner = IPFSProvider(simulate=True)
        enc = EncryptedStorage(inner, master_key="test-key-123")

        original = b"secret data for cold storage"
        cid = await enc.store(original, {})
        assert cid  # CID получен

        decrypted = await enc.retrieve(cid)
        assert decrypted == original

    @pytest.mark.asyncio
    async def test_encrypted_data_differs_from_original(self):
        inner = IPFSProvider(simulate=True)
        enc = EncryptedStorage(inner, master_key="key")

        original = b"sensitive info"
        await enc.store(original, {})

        # Внутренний store получил зашифрованные данные (не оригинал)
        stored_values = list(inner._sim_store.values())
        assert len(stored_values) == 1
        assert stored_values[0] != original

    @pytest.mark.asyncio
    async def test_exists_proxied(self):
        inner = IPFSProvider(simulate=True)
        enc = EncryptedStorage(inner, master_key="k")
        cid = await enc.store(b"x", {})
        assert await enc.exists(cid) is True
        assert await enc.exists("fake") is False


# ── ArchiveRecord ─────────────────────────────────────────────────────────


class TestArchiveRecord:
    def test_to_dict(self):
        r = ArchiveRecord(
            ref="ref:file:abc",
            cold_id="bafyxyz",
            provider="ipfs",
            importance=0.95,
            archived_at=1700000000.0,
            size_bytes=1024,
            encrypted=True,
        )
        d = r.to_dict()
        assert d["ref"] == "ref:file:abc"
        assert d["cold_id"] == "bafyxyz"
        assert d["encrypted"] is True

    def test_from_dict(self):
        d = {"ref": "r", "cold_id": "c", "provider": "arweave", "importance": 0.8}
        r = ArchiveRecord.from_dict(d)
        assert r.provider == "arweave"
        assert r.importance == 0.8

    def test_roundtrip(self):
        r = ArchiveRecord(ref="r", cold_id="c", provider="ipfs", size_bytes=42)
        r2 = ArchiveRecord.from_dict(r.to_dict())
        assert r2.ref == r.ref
        assert r2.size_bytes == 42


# ── ImmortalMemoryManager ────────────────────────────────────────────────


@pytest.fixture
def manager_with_ipfs(tmp_path):
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.repository import MemoryRepository
    from swarm.memory.vector_store import VectorStore

    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)
    ipfs = IPFSProvider(simulate=True)
    vs = VectorStore()
    return ImmortalMemoryManager(vs, repo, ipfs, provider_name="ipfs")


@pytest.fixture
def manager_no_cold(tmp_path):
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.repository import MemoryRepository
    from swarm.memory.vector_store import VectorStore

    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)
    vs = VectorStore()
    return ImmortalMemoryManager(vs, repo, cold_storage=None)


class TestImmortalMemoryManager:
    @pytest.mark.asyncio
    async def test_archive_success(self, manager_with_ipfs):
        mgr = manager_with_ipfs
        # Создаём артефакт в warm layer
        ref = await mgr.repo.save(
            data={"text": "важная информация"},
            table="notes",
            tags=["important"],
        )

        record = await mgr.archive(ref, importance=0.9)
        assert record is not None
        assert record.cold_id.startswith("bafy")
        assert record.provider == "ipfs"
        assert record.size_bytes > 0

    @pytest.mark.asyncio
    async def test_archive_low_importance_skipped(self, manager_with_ipfs):
        mgr = manager_with_ipfs
        ref = await mgr.repo.save(data={"x": 1}, table="t")
        record = await mgr.archive(ref, importance=0.2, min_importance=0.5)
        assert record is None

    @pytest.mark.asyncio
    async def test_archive_no_cold_storage(self, manager_no_cold):
        mgr = manager_no_cold
        ref = await mgr.repo.save(data={"x": 1}, table="t")
        record = await mgr.archive(ref, importance=1.0)
        assert record is None

    @pytest.mark.asyncio
    async def test_archive_creates_log_entry(self, manager_with_ipfs):
        mgr = manager_with_ipfs
        ref = await mgr.repo.save(data={"data": "to archive"}, table="docs")
        await mgr.archive(ref, importance=0.9)

        log = await mgr.archive_log()
        assert len(log) == 1
        assert log[0].ref == ref
        assert log[0].provider == "ipfs"

    @pytest.mark.asyncio
    async def test_restore(self, manager_with_ipfs):
        mgr = manager_with_ipfs
        ref = await mgr.repo.save(data={"restore": "me"}, table="t")
        record = await mgr.archive(ref, importance=1.0)
        assert record is not None

        restored = await mgr.restore(record.cold_id)
        assert restored is not None
        assert b"restore" in restored

    @pytest.mark.asyncio
    async def test_restore_no_cold(self, manager_no_cold):
        result = await manager_no_cold.restore("some_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_check(self, manager_with_ipfs):
        mgr = manager_with_ipfs
        ref = await mgr.repo.save(data={"check": "this"}, table="t")
        record = await mgr.archive(ref, importance=1.0)
        assert record is not None

        assert await mgr.check(record.cold_id) is True
        assert await mgr.check("nonexistent") is False

    @pytest.mark.asyncio
    async def test_check_no_cold(self, manager_no_cold):
        assert await manager_no_cold.check("x") is False

    @pytest.mark.asyncio
    async def test_archive_log_empty(self, manager_with_ipfs):
        log = await manager_with_ipfs.archive_log()
        assert log == []

    @pytest.mark.asyncio
    async def test_stats(self, manager_with_ipfs):
        s = manager_with_ipfs.stats()
        assert s["provider"] == "ipfs"
        assert s["cold_available"] is True

    @pytest.mark.asyncio
    async def test_stats_no_cold(self, manager_no_cold):
        s = manager_no_cold.stats()
        assert s["cold_available"] is False

    @pytest.mark.asyncio
    async def test_archive_nonexistent_ref(self, manager_with_ipfs):
        record = await manager_with_ipfs.archive("ref:file:nonexistent", importance=1.0)
        assert record is None

    @pytest.mark.asyncio
    async def test_encrypted_archive(self, tmp_path):
        from swarm.memory.adapters.local_scratch import LocalScratchAdapter
        from swarm.memory.composite import CompositeMemoryPort
        from swarm.memory.repository import MemoryRepository
        from swarm.memory.vector_store import VectorStore

        port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
        repo = MemoryRepository(port)
        ipfs = IPFSProvider(simulate=True)
        enc = EncryptedStorage(ipfs, master_key="secret")
        vs = VectorStore()
        mgr = ImmortalMemoryManager(vs, repo, enc, provider_name="ipfs", encrypted=True)

        ref = await repo.save(data={"secret": "data"}, table="confidential")
        record = await mgr.archive(ref, importance=1.0)
        assert record is not None
        assert record.encrypted is True

        # Восстанавливаем через encrypted provider
        restored = await mgr.restore(record.cold_id)
        assert restored is not None
        assert b"secret" in restored

    @pytest.mark.asyncio
    async def test_multiple_archives(self, manager_with_ipfs):
        mgr = manager_with_ipfs
        refs = []
        for i in range(5):
            ref = await mgr.repo.save(data={"i": i}, table="batch")
            refs.append(ref)
            await mgr.archive(ref, importance=0.9)

        log = await mgr.archive_log(limit=10)
        assert len(log) == 5
