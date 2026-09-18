"""SQL gateway -- one-way mirror of :class:`MemoryRepository` into SQLite.

Memory repository is the source of truth; the SQLite database is a
read-side projection that lets operators run arbitrary SQL (joins, GROUP
BY, window functions, …) without writing a Python query DSL on top of
the in-memory dict-and-tag world.

Schema
~~~~~~

Two tables, plus a couple of generated columns for the most common
filters:

``records``
    +---------------+------------------------------------------------+
    | Column        | Description                                    |
    +===============+================================================+
    | ``ref``       | Primary key.  Identical to repository ref.     |
    +---------------+------------------------------------------------+
    | ``table_name``| Logical table name (``attrs._table``).         |
    +---------------+------------------------------------------------+
    | ``ts``        | Wall-clock ``attrs._ts`` (REAL).               |
    +---------------+------------------------------------------------+
    | ``attrs_json``| JSON blob of all artifact attrs.               |
    +---------------+------------------------------------------------+
    | ``tags_json`` | JSON array of all tags.                        |
    +---------------+------------------------------------------------+
    | ``data_json`` | JSON blob of the row payload.                  |
    +---------------+------------------------------------------------+

``record_tags``
    +---------------+------------------------------------------------+
    | Column        | Description                                    |
    +===============+================================================+
    | ``ref``       | FK -> records.ref                              |
    +---------------+------------------------------------------------+
    | ``tag``       | A single tag literal.                          |
    +---------------+------------------------------------------------+

Indexes on ``records(table_name)``, ``records(ts)`` and
``record_tags(tag)`` so the common filters scale.

Workflow
~~~~~~~~

.. code-block:: python

    mirror = SqlMirror.open("/tmp/mirror.db")
    await mirror.sync(repo)             # rebuild mirror from scratch
    cur = mirror.execute("SELECT COUNT(*) FROM records WHERE table_name=?", ("notes",))
    print(cur.fetchone())
    mirror.close()
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    ref         TEXT PRIMARY KEY,
    table_name  TEXT,
    ts          REAL,
    attrs_json  TEXT,
    tags_json   TEXT,
    data_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_table ON records(table_name);
CREATE INDEX IF NOT EXISTS idx_records_ts    ON records(ts);

CREATE TABLE IF NOT EXISTS record_tags (
    ref TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (ref, tag)
);
CREATE INDEX IF NOT EXISTS idx_record_tags_tag ON record_tags(tag);
"""


class SqlMirror:
    """Thin SQLite mirror over a :class:`MemoryRepository`.

    Open with :meth:`open` (file-backed) or :meth:`open_memory` (in-RAM,
    useful for tests).  Always call :meth:`close` when done.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @classmethod
    def open(cls, path: str | Path) -> SqlMirror:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(sqlite3.connect(str(path)))

    @classmethod
    def open_memory(cls) -> SqlMirror:
        return cls(sqlite3.connect(":memory:"))

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    async def sync(self, repo, *, batch_limit: int = 100_000) -> int:
        """Drop and rebuild the mirror from every row in ``repo``.

        Returns the number of rows written.
        """
        rows = await repo.query(limit=batch_limit)
        self._conn.execute("DELETE FROM record_tags")
        self._conn.execute("DELETE FROM records")
        self._bulk_insert(rows)
        self._conn.commit()
        return len(rows)

    async def upsert(self, repo, refs: Iterable[str]) -> int:
        """Refresh a specific subset of refs.

        For each ref, fetches the underlying artifact via repo's port,
        re-decodes the row, and replaces the SQLite row.  Missing refs
        are silently skipped.  Returns the number of rows successfully
        upserted.
        """
        count = 0
        for ref in refs:
            try:
                rows = await repo.query(limit=100_000)
                row = next((r for r in rows if r.ref == ref), None)
            except Exception:
                row = None
            if row is None:
                continue
            self._delete_one(ref)
            self._bulk_insert([row])
            count += 1
        self._conn.commit()
        return count

    def _bulk_insert(self, rows: Iterable) -> None:
        record_rows: list[tuple] = []
        tag_rows: list[tuple] = []
        for r in rows:
            attrs = dict(r.attrs or {})
            tags = list(r.tags or [])
            data = dict(r.data or {})
            ts = attrs.get("_ts")
            table_name = attrs.get("_table")
            record_rows.append(
                (
                    r.ref,
                    table_name,
                    float(ts) if isinstance(ts, (int, float)) else None,
                    json.dumps(attrs, ensure_ascii=False, sort_keys=True),
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(data, ensure_ascii=False),
                )
            )
            for tag in tags:
                tag_rows.append((r.ref, str(tag)))
        if record_rows:
            self._conn.executemany(
                "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?, ?, ?)",
                record_rows,
            )
        if tag_rows:
            self._conn.executemany(
                "INSERT OR REPLACE INTO record_tags(ref, tag) VALUES (?, ?)",
                tag_rows,
            )

    def _delete_one(self, ref: str) -> None:
        self._conn.execute("DELETE FROM record_tags WHERE ref = ?", (ref,))
        self._conn.execute("DELETE FROM records WHERE ref = ?", (ref,))

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, tuple(params))

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        cur = self.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    def count_records(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM records")
        return int(cur.fetchone()[0])

    def tables(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT table_name FROM records "
            "WHERE table_name IS NOT NULL ORDER BY table_name"
        )
        return [row[0] for row in cur.fetchall()]

    def distinct_tags(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT tag FROM record_tags ORDER BY tag"
        )
        return [row[0] for row in cur.fetchall()]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.fetchall("SELECT * FROM records"))

    def close(self) -> None:
        self._conn.close()


__all__ = ["SqlMirror"]
