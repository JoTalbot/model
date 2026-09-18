"""CRDT primitives and memory index for multi-device sync.

Provides:
- ``LWWRegister`` — Last-Write-Wins register
- ``GSet`` — Grow-only set
- ``MemoryIndexCRDT`` — composite CRDT that tracks all refs + metadata

All operations are conflict-free: any merge order yields the same result.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LWWRegister:
    """Last-Write-Wins Register CRDT."""

    value: Any
    timestamp: float

    def merge(self, other: LWWRegister) -> None:
        if other.timestamp > self.timestamp:
            self.value = other.value
            self.timestamp = other.timestamp
        elif other.timestamp == self.timestamp:
            # Детерминированный tiebreak по repr
            if repr(other.value) > repr(self.value):
                self.value = other.value
                self.timestamp = other.timestamp


@dataclass
class GSet:
    """Grow-only Set CRDT."""

    elements: set[str] = field(default_factory=set)

    def add(self, element: str) -> None:
        self.elements.add(element)

    def merge(self, other: GSet) -> None:
        self.elements.update(other.elements)

    def __contains__(self, item: str) -> bool:
        return item in self.elements

    def __len__(self) -> int:
        return len(self.elements)


class MemoryIndexCRDT:
    """CRDT-индекс памяти для синхронизации между устройствами.

    Отслеживает:
    - ``records``: ref → LWWRegister(metadata) — метаданные каждого артефакта
    - ``deleted``: GSet — удалённые ref'ы (tombstone, необратимо)
    - ``all_refs``: GSet — все когда-либо виденные ref'ы
    """

    def __init__(self) -> None:
        self.records: dict[str, LWWRegister] = {}
        self.deleted: GSet = GSet()
        self.all_refs: GSet = GSet()
        self._version: int = 0  # локальный счётчик для delta-sync

    def update_record(self, ref: str, data: Any, *, ts: float | None = None) -> None:
        """Обновить/добавить запись."""
        ts = ts or time.time()
        if ref in self.records:
            self.records[ref].merge(LWWRegister(data, ts))
        else:
            self.records[ref] = LWWRegister(data, ts)
        self.all_refs.add(ref)
        self._version += 1

    def delete_record(self, ref: str) -> None:
        """Удалить запись (tombstone — необратимо)."""
        self.deleted.add(ref)
        self._version += 1

    def get_active_refs(self) -> list[str]:
        """Все живые (не удалённые) ref'ы."""
        return [r for r in self.all_refs.elements if r not in self.deleted.elements]

    def get_record(self, ref: str) -> Any | None:
        """Получить метаданные по ref."""
        reg = self.records.get(ref)
        if reg is None or ref in self.deleted.elements:
            return None
        return reg.value

    @property
    def version(self) -> int:
        return self._version

    @property
    def active_count(self) -> int:
        return len(self.get_active_refs())

    def merge(self, other: MemoryIndexCRDT) -> int:
        """Мержим другой CRDT-индекс в текущий. Возвращает кол-во изменений."""
        changes = 0

        # Merge all_refs (grow-only)
        before = len(self.all_refs)
        self.all_refs.merge(other.all_refs)
        changes += len(self.all_refs) - before

        # Merge deleted (grow-only)
        before_del = len(self.deleted)
        self.deleted.merge(other.deleted)
        changes += len(self.deleted) - before_del

        # Merge records (LWW)
        for ref, other_reg in other.records.items():
            if ref in self.records:
                old_val = self.records[ref].value
                old_ts = self.records[ref].timestamp
                self.records[ref].merge(other_reg)
                if self.records[ref].value != old_val or self.records[ref].timestamp != old_ts:
                    changes += 1
            else:
                self.records[ref] = LWWRegister(other_reg.value, other_reg.timestamp)
                changes += 1

        if changes > 0:
            self._version += 1

        return changes

    def serialize(self) -> dict:
        """Сериализовать в JSON-совместимый dict для передачи по сети."""
        return {
            "records": {
                ref: {"v": reg.value, "t": reg.timestamp}
                for ref, reg in self.records.items()
            },
            "deleted": sorted(self.deleted.elements),
            "all_refs": sorted(self.all_refs.elements),
            "version": self._version,
        }

    @classmethod
    def deserialize(cls, data: dict) -> MemoryIndexCRDT:
        """Десериализовать из dict (обратная к serialize)."""
        crdt = cls()

        for ref, rec in (data.get("records") or {}).items():
            crdt.records[ref] = LWWRegister(
                value=rec.get("v"),
                timestamp=float(rec.get("t", 0)),
            )

        for ref in data.get("deleted") or []:
            crdt.deleted.add(ref)

        for ref in data.get("all_refs") or []:
            crdt.all_refs.add(ref)

        crdt._version = int(data.get("version", 0))
        return crdt

    def delta_since(self, other_refs: set[str]) -> dict:
        """Вернуть delta — только записи, которых нет у другой стороны.

        ``other_refs`` — множество ref'ов, которые уже есть на другом узле.
        """
        missing_refs = self.all_refs.elements - other_refs
        return {
            "records": {
                ref: {"v": self.records[ref].value, "t": self.records[ref].timestamp}
                for ref in missing_refs
                if ref in self.records
            },
            "deleted": sorted(self.deleted.elements - other_refs),
            "all_refs": sorted(missing_refs),
            "version": self._version,
        }

    def stats(self) -> dict:
        """Снимок статистики для мониторинга."""
        return {
            "total_refs": len(self.all_refs),
            "active_refs": self.active_count,
            "deleted_refs": len(self.deleted),
            "records_count": len(self.records),
            "version": self._version,
        }
