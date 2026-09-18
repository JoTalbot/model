from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from swarm.memory.types import Artifact


@dataclass
class MemoryRow:
    ref: str
    table: str
    data: dict[str, Any]
    tags: list[str]
    attrs: dict[str, Any]


class MemoryRepository:
    _WHERE_CLAUSE_RE = re.compile(
        r"^\s*(data|attrs|table)(?:\.([A-Za-z_][A-Za-z0-9_]*))?\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$"
    )

    """DB-like helper over MemoryPort for structured records."""

    def __init__(self, memory_port) -> None:
        self._port = memory_port

    async def save(
        self,
        data: dict[str, Any],
        *,
        table: str,
        tags: list[str] | None = None,
        attrs: dict[str, Any] | None = None, store: str | None = None,
    ) -> str:
        merged_attrs = {
            "schema_version": 1,
            "kind": "record",
            "_table": table,
            "_ts": time.time(),
            **(attrs or {}),
        }
        merged_tags = list(tags or [])
        table_tag = f"table:{table}"
        if table_tag not in merged_tags:
            merged_tags.append(table_tag)

        artifact = Artifact(
            content=json.dumps(data, ensure_ascii=False),
            mime="application/json",
            tags=merged_tags,
            provenance={},
            attrs=merged_attrs,
        )
        if store: artifact.attrs["store"] = store
        return await self._port.put(artifact)

    async def count(
        self,
        *,
        table: str | None = None,
        tags: list[str] | None = None,
        text: str | None = None,
        attrs: dict[str, Any] | None = None, store: str | None = None,
        where: str | None = None,
    ) -> int:
        """Return the number of rows matching the same filter set as ``query``.

        ``offset``/``limit`` are intentionally bypassed.
        """
        rows = await self.query(
            table=table,
            tags=tags,
            text=text,
            attrs=attrs,
            where=where,
            limit=10_000_000,
        )
        return len(rows)

    async def distinct(
        self,
        path: str,
        *,
        table: str | None = None,
        tags: list[str] | None = None,
        text: str | None = None,
        attrs: dict[str, Any] | None = None, store: str | None = None,
        where: str | None = None,
    ) -> list[Any]:
        """Return the distinct values of ``data.<key>`` / ``attrs.<key>``.

        ``path`` follows the same dotted syntax used by ``order_by`` / ``where``.
        Order is preserved (first-seen wins) so the caller controls it via
        ``order_by`` on a follow-up ``query`` call when stability matters.
        """
        if path != "table" and not (
            path.startswith("data.") or path.startswith("attrs.")
        ):
            raise ValueError(f"unsupported distinct path: {path}")
        rows = await self.query(
            table=table,
            tags=tags,
            text=text,
            attrs=attrs,
            where=where,
            limit=10_000_000,
        )
        seen: list[Any] = []
        seen_set: set[Any] = set()
        for r in rows:
            v = self._field_value(r, path)
            key: Any
            try:
                hash(v)
                key = v
            except TypeError:
                key = repr(v)
            if key in seen_set:
                continue
            seen_set.add(key)
            seen.append(v)
        return seen

    async def latest(
        self,
        *,
        table: str | None = None,
        tags: list[str] | None = None,
        attrs: dict[str, Any] | None = None, store: str | None = None,
        where: str | None = None,
        n: int = 1,
    ) -> list[MemoryRow]:
        """Return the ``n`` most recent rows (by ``attrs._ts`` if present).

        Rows without a ``_ts`` field sort to the bottom of the result.
        """
        rows = await self.query(
            table=table,
            tags=tags,
            attrs=attrs,
            where=where,
            limit=10_000_000,
        )
        rows.sort(key=lambda r: r.attrs.get("_ts", 0), reverse=True)
        if n < 0:
            n = 0
        return rows[:n]

    async def delete(self, ref: str) -> bool:
        """Delete a record by ref. Returns False if the adapter does not support it."""
        try:
            return await self._port.delete(ref)
        except Exception:
            return False

    async def query(
        self,
        *,
        table: str | None = None,
        tags: list[str] | None = None,
        text: str | None = None,
        attrs: dict[str, Any] | None = None, store: str | None = None,
        where: str | None = None,
        order_by: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[MemoryRow]:
        seed_tags = list(tags or [])
        if table:
            table_tag = f"table:{table}"
            if table_tag not in seed_tags:
                seed_tags.append(table_tag)

        metas = await self._port.search(seed_tags, owner=None)
        matched: list[MemoryRow] = []
        needle = text.casefold() if text else None
        want_attrs = attrs or {}

        for meta in metas:
            art = await self._port.get(meta.ref)
            try:
                payload = art.content.decode("utf-8") if isinstance(art.content, bytes) else art.content
                data = json.loads(payload)
            except Exception:
                continue
            row_attrs = dict(art.attrs or {})
            row_table = str(row_attrs.get("_table") or "")
            if table and row_table != table:
                continue
            if any(row_attrs.get(k) != v for k, v in want_attrs.items()):
                continue
            if needle and needle not in json.dumps(data, ensure_ascii=False).casefold():
                continue
            row = MemoryRow(
                ref=meta.ref,
                table=row_table,
                data=data,
                tags=list(art.tags),
                attrs=row_attrs,
            )
            if where and not self._matches_where(row, where):
                continue
            matched.append(
                MemoryRow(
                    ref=row.ref,
                    table=row.table,
                    data=row.data,
                    tags=row.tags,
                    attrs=row.attrs,
                )
            )
        if order_by:
            path, desc = self._parse_order(order_by)
            matched.sort(key=lambda r: self._sort_value(self._field_value(r, path)), reverse=desc)
        if offset < 0:
            offset = 0
        return matched[offset : offset + max(0, limit)]

    def _sort_value(self, v: Any) -> tuple[int, Any]:
        if v is None:
            return (1, "")
        return (0, v)

    def _field_value(self, row: MemoryRow, path: str) -> Any:
        if path == "table":
            return row.table
        prefix, _, key = path.partition(".")
        if prefix == "data":
            return row.data.get(key)
        if prefix == "attrs":
            return row.attrs.get(key)
        raise ValueError(f"unsupported field path: {path}")

    def _parse_order(self, order_by: str) -> tuple[str, bool]:
        raw = order_by.strip()
        if ":" in raw:
            path, direction = raw.split(":", 1)
        else:
            path, direction = raw, "asc"
        path = path.strip()
        desc = direction.strip().lower() == "desc"
        if path not in {"table"} and not (
            path.startswith("data.") or path.startswith("attrs.")
        ):
            raise ValueError(f"unsupported order_by field: {path}")
        return path, desc

    def _parse_where_literal(self, token: str) -> Any:
        t = token.strip()
        if t.lower() in {"true", "false"}:
            return t.lower() == "true"
        if t.lower() == "null":
            return None
        if (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
            return t[1:-1]
        try:
            if "." in t:
                return float(t)
            return int(t)
        except ValueError:
            return t

    def _compare(self, left: Any, op: str, right: Any) -> bool:
        try:
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == ">=":
                return left >= right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            if op == "<":
                return left < right
        except TypeError:
            return False
        return False

    def _matches_where(self, row: MemoryRow, where: str) -> bool:
        clauses = [c.strip() for c in where.split(" and ") if c.strip()]
        for clause in clauses:
            m = self._WHERE_CLAUSE_RE.match(clause)
            if not m:
                return False
            root, field, op, rhs = m.groups()
            path = root if field is None else f"{root}.{field}"
            left = self._field_value(row, path)
            right = self._parse_where_literal(rhs)
            if not self._compare(left, op, right):
                return False
        return True
