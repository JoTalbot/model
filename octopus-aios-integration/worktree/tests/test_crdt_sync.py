"""Тесты для swarm.memory.crdt и swarm.memory.sync."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.memory.crdt import GSet, LWWRegister, MemoryIndexCRDT
from swarm.memory.sync import GOSSIP_MSG_TYPE, SyncEngine

# ── LWWRegister ────────────────────────────────────────────────────────


class TestLWWRegister:
    def test_merge_newer_wins(self):
        a = LWWRegister(value="old", timestamp=1.0)
        b = LWWRegister(value="new", timestamp=2.0)
        a.merge(b)
        assert a.value == "new"
        assert a.timestamp == 2.0

    def test_merge_older_loses(self):
        a = LWWRegister(value="current", timestamp=5.0)
        b = LWWRegister(value="old", timestamp=3.0)
        a.merge(b)
        assert a.value == "current"
        assert a.timestamp == 5.0

    def test_merge_same_timestamp_deterministic(self):
        a = LWWRegister(value="aaa", timestamp=1.0)
        b = LWWRegister(value="zzz", timestamp=1.0)
        a.merge(b)
        # "zzz" > "aaa" по repr, поэтому b побеждает
        assert a.value == "zzz"

    def test_merge_same_timestamp_reverse(self):
        a = LWWRegister(value="zzz", timestamp=1.0)
        b = LWWRegister(value="aaa", timestamp=1.0)
        a.merge(b)
        # "zzz" > "aaa", поэтому a остаётся
        assert a.value == "zzz"


# ── GSet ───────────────────────────────────────────────────────────────


class TestGSet:
    def test_add_and_contains(self):
        s = GSet()
        s.add("x")
        assert "x" in s
        assert "y" not in s

    def test_merge(self):
        a = GSet(elements={"x", "y"})
        b = GSet(elements={"y", "z"})
        a.merge(b)
        assert a.elements == {"x", "y", "z"}

    def test_len(self):
        s = GSet(elements={"a", "b", "c"})
        assert len(s) == 3

    def test_grow_only(self):
        """GSet не поддерживает удаление — только рост."""
        s = GSet(elements={"a"})
        s.elements.discard("a")  # Прямое удаление — работает на уровне set
        # Но после merge — элемент вернётся
        other = GSet(elements={"a"})
        s.merge(other)
        assert "a" in s


# ── MemoryIndexCRDT ────────────────────────────────────────────────────


class TestMemoryIndexCRDT:
    def test_update_and_get(self):
        crdt = MemoryIndexCRDT()
        crdt.update_record("ref:1", {"table": "notes"})
        assert crdt.get_record("ref:1") == {"table": "notes"}
        assert crdt.active_count == 1

    def test_delete(self):
        crdt = MemoryIndexCRDT()
        crdt.update_record("ref:1", {"table": "notes"})
        crdt.delete_record("ref:1")
        assert crdt.get_record("ref:1") is None
        assert crdt.active_count == 0
        assert len(crdt.all_refs) == 1  # ref остаётся в all_refs

    def test_get_active_refs(self):
        crdt = MemoryIndexCRDT()
        crdt.update_record("ref:a", {})
        crdt.update_record("ref:b", {})
        crdt.update_record("ref:c", {})
        crdt.delete_record("ref:b")
        active = crdt.get_active_refs()
        assert sorted(active) == ["ref:a", "ref:c"]

    def test_version_increments(self):
        crdt = MemoryIndexCRDT()
        assert crdt.version == 0
        crdt.update_record("r", {})
        assert crdt.version == 1
        crdt.delete_record("r")
        assert crdt.version == 2

    def test_serialize_deserialize_roundtrip(self):
        crdt = MemoryIndexCRDT()
        crdt.update_record("ref:1", {"key": "val"}, ts=100.0)
        crdt.update_record("ref:2", {"key": "val2"}, ts=200.0)
        crdt.delete_record("ref:1")

        data = crdt.serialize()
        restored = MemoryIndexCRDT.deserialize(data)

        assert restored.get_record("ref:1") is None  # удалён
        assert restored.get_record("ref:2") == {"key": "val2"}
        assert sorted(restored.all_refs.elements) == ["ref:1", "ref:2"]
        assert "ref:1" in restored.deleted

    def test_merge_two_crdts(self):
        a = MemoryIndexCRDT()
        a.update_record("ref:1", {"from": "a"}, ts=1.0)
        a.update_record("ref:2", {"from": "a"}, ts=2.0)

        b = MemoryIndexCRDT()
        b.update_record("ref:2", {"from": "b"}, ts=3.0)  # новее
        b.update_record("ref:3", {"from": "b"}, ts=4.0)

        changes = a.merge(b)
        assert changes > 0
        # ref:1 — только в a, осталось
        assert a.get_record("ref:1") == {"from": "a"}
        # ref:2 — b новее (ts=3 > ts=2)
        assert a.get_record("ref:2") == {"from": "b"}
        # ref:3 — новое из b
        assert a.get_record("ref:3") == {"from": "b"}

    def test_merge_is_commutative(self):
        """a.merge(b) и b.merge(a) дают одинаковый результат."""
        a = MemoryIndexCRDT()
        a.update_record("r1", "A", ts=1.0)
        a.update_record("r2", "A2", ts=3.0)

        b = MemoryIndexCRDT()
        b.update_record("r1", "B", ts=2.0)
        b.update_record("r3", "B3", ts=4.0)

        # Клонируем через serialize/deserialize
        a1 = MemoryIndexCRDT.deserialize(a.serialize())
        b1 = MemoryIndexCRDT.deserialize(b.serialize())
        a2 = MemoryIndexCRDT.deserialize(a.serialize())
        b2 = MemoryIndexCRDT.deserialize(b.serialize())

        a1.merge(b1)
        b2.merge(a2)

        assert a1.get_record("r1") == b2.get_record("r1")
        assert a1.get_record("r2") == b2.get_record("r2")
        assert a1.get_record("r3") == b2.get_record("r3")
        assert sorted(a1.get_active_refs()) == sorted(b2.get_active_refs())

    def test_merge_idempotent(self):
        """Повторный merge не меняет состояние."""
        a = MemoryIndexCRDT()
        a.update_record("r", "x", ts=1.0)

        b = MemoryIndexCRDT()
        b.update_record("r", "x", ts=1.0)

        a.merge(b)
        v_after_first = a.version
        changes2 = a.merge(b)

        assert changes2 == 0
        assert a.version == v_after_first

    def test_merge_with_deletes(self):
        a = MemoryIndexCRDT()
        a.update_record("r1", "alive")

        b = MemoryIndexCRDT()
        b.update_record("r1", "alive")
        b.delete_record("r1")

        a.merge(b)
        assert a.get_record("r1") is None  # tombstone от b

    def test_delta_since(self):
        crdt = MemoryIndexCRDT()
        crdt.update_record("r1", "a", ts=1.0)
        crdt.update_record("r2", "b", ts=2.0)
        crdt.update_record("r3", "c", ts=3.0)

        # Другая сторона уже имеет r1 и r2
        delta = crdt.delta_since({"r1", "r2"})
        assert "r3" in delta["all_refs"]
        assert "r1" not in delta["all_refs"]

    def test_stats(self):
        crdt = MemoryIndexCRDT()
        crdt.update_record("r1", {})
        crdt.update_record("r2", {})
        crdt.delete_record("r1")

        s = crdt.stats()
        assert s["total_refs"] == 2
        assert s["active_refs"] == 1
        assert s["deleted_refs"] == 1
        assert s["records_count"] == 2

    def test_deserialize_empty(self):
        crdt = MemoryIndexCRDT.deserialize({})
        assert crdt.active_count == 0
        assert crdt.version == 0


# ── SyncEngine ─────────────────────────────────────────────────────────


class TestSyncEngine:
    def test_track_put(self):
        engine = SyncEngine("node-1")
        engine.track_put("ref:a", {"table": "notes"})
        assert engine.crdt.get_record("ref:a") is not None
        assert engine.crdt.active_count == 1

    def test_track_delete(self):
        engine = SyncEngine("node-1")
        engine.track_put("ref:a")
        engine.track_delete("ref:a")
        assert engine.crdt.active_count == 0

    def test_missing_refs(self):
        engine = SyncEngine("node-1")
        engine.track_put("ref:a")
        engine.track_put("ref:b")
        engine.track_put("ref:c")

        local = {"ref:a"}
        missing = engine.missing_refs(local)
        assert sorted(missing) == ["ref:b", "ref:c"]

    def test_stats(self):
        engine = SyncEngine("node-1", sync_interval=60.0)
        engine.track_put("ref:x")
        s = engine.stats()
        assert s["node_id"] == "node-1"
        assert s["active_refs"] == 1
        assert s["sync_interval"] == 60.0
        assert s["gossip_connected"] is False

    @pytest.mark.asyncio
    async def test_broadcast_without_gossip(self):
        """Без gossip broadcast ничего не делает (не крашится)."""
        engine = SyncEngine("node-1")
        engine.track_put("ref:a")
        await engine.broadcast_state()  # не падает

    @pytest.mark.asyncio
    async def test_broadcast_with_gossip(self):
        gossip = AsyncMock()
        gossip.inject = AsyncMock()

        engine = SyncEngine("node-1", gossip=gossip)
        engine.track_put("ref:a")
        await engine.broadcast_state()

        gossip.inject.assert_called_once()
        msg = gossip.inject.call_args[0][0]
        assert msg.msg_type == GOSSIP_MSG_TYPE
        assert msg.payload["from_node"] == "node-1"
        assert "crdt" in msg.payload

    @pytest.mark.asyncio
    async def test_handle_gossip_merges(self):
        engine = SyncEngine("node-1")
        engine.track_put("ref:local")

        # Создаём удалённый CRDT с другой записью
        remote = MemoryIndexCRDT()
        remote.update_record("ref:remote", {"from": "node-2"})

        # Создаём mock gossip message
        msg = MagicMock()
        msg.msg_type = GOSSIP_MSG_TYPE
        msg.payload = {
            "from_node": "node-2",
            "crdt": remote.serialize(),
        }

        await engine.handle_gossip(msg)

        # Теперь у нас есть оба ref'а
        assert engine.crdt.active_count == 2
        assert engine.crdt.get_record("ref:remote") is not None
        assert engine.stats()["merge_count"] == 1

    @pytest.mark.asyncio
    async def test_handle_gossip_wrong_type_ignored(self):
        engine = SyncEngine("node-1")
        msg = MagicMock()
        msg.msg_type = "other_type"
        msg.payload = {}

        await engine.handle_gossip(msg)
        assert engine.stats()["merge_count"] == 0

    @pytest.mark.asyncio
    async def test_handle_gossip_empty_crdt(self):
        engine = SyncEngine("node-1")
        msg = MagicMock()
        msg.msg_type = GOSSIP_MSG_TYPE
        msg.payload = {"from_node": "n2", "crdt": None}

        await engine.handle_gossip(msg)
        assert engine.stats()["merge_count"] == 0

    @pytest.mark.asyncio
    async def test_two_engines_sync(self):
        """Полный цикл: два узла синхронизируются через gossip."""
        # Узел 1 создаёт записи
        e1 = SyncEngine("node-1")
        e1.track_put("ref:a", {"table": "notes"})
        e1.track_put("ref:b", {"table": "parts"})

        # Узел 2 создаёт свои записи
        e2 = SyncEngine("node-2")
        e2.track_put("ref:c", {"table": "notes"})
        e2.track_delete("ref:x")  # удалил что-то неизвестное

        # Узел 1 → Узел 2 (через serialize/deserialize)
        msg1 = MagicMock()
        msg1.msg_type = GOSSIP_MSG_TYPE
        msg1.payload = {
            "from_node": "node-1",
            "crdt": e1.crdt.serialize(),
        }
        await e2.handle_gossip(msg1)

        # Узел 2 → Узел 1
        msg2 = MagicMock()
        msg2.msg_type = GOSSIP_MSG_TYPE
        msg2.payload = {
            "from_node": "node-2",
            "crdt": e2.crdt.serialize(),
        }
        await e1.handle_gossip(msg2)

        # После синхронизации оба видят все ref'ы
        assert sorted(e1.crdt.get_active_refs()) == sorted(e2.crdt.get_active_refs())
        assert e1.crdt.active_count == 3  # a, b, c (x удалён, но его и не было как active)

    @pytest.mark.asyncio
    async def test_start_stop(self):
        engine = SyncEngine("n", sync_interval=0.01)
        await engine.start()
        assert engine._task is not None
        await engine.stop()
        assert engine._task.cancelled() or engine._task.done()
