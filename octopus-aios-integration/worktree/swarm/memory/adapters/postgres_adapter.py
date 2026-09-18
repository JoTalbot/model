"""
swarm/memory/adapters/postgres_adapter.py
─────────────────────────────────────────
PostgreSQL-адаптер для MemoryPort.
Хранит артефакты в таблице octopus_artifacts в octopus_db.
Совместим с LocalScratchAdapter интерфейсом.

Использование в config.yaml:
  memory_facade:
    scratch_root: postgres://octopus_user:octopus_pass@127.0.0.1:5432/octopus_db
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS octopus_artifacts (
    ref         TEXT PRIMARY KEY,
    table_name  TEXT NOT NULL DEFAULT 'default',
    content     TEXT,
    mime        TEXT DEFAULT 'text/plain',
    tags        JSONB DEFAULT '[]',
    attrs       JSONB DEFAULT '{}',
    size_bytes  INTEGER DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_artifacts_table ON octopus_artifacts(table_name);
CREATE INDEX IF NOT EXISTS idx_artifacts_created ON octopus_artifacts(created_at DESC);
"""


class PostgreSQLAdapter:
    """
    Адаптер хранилища на PostgreSQL.
    Drop-in замена LocalScratchAdapter.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn = None
        self._ensure_schema()

    def _connect(self):
        if self._conn is None or self._conn.closed:
            try:
                import psycopg2
                import psycopg2.extras
                self._conn = psycopg2.connect(self._dsn)
                self._conn.autocommit = True
                logger.info("PostgreSQLAdapter: connected to %s", self._dsn.split('@')[-1])
            except ImportError:
                raise RuntimeError("psycopg2 not installed. Run: pip install psycopg2-binary")
        return self._conn

    def _ensure_schema(self) -> None:
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
            logger.info("PostgreSQLAdapter: schema ready")
        except Exception as e:
            logger.warning("PostgreSQLAdapter: schema init error: %s", e)

    # ── MemoryPort interface ──────────────────────────────────────────────────

    async def put(self, artifact) -> str:
        """Сохранить артефакт, вернуть ref."""
        ref = f"ref:postgres:{uuid.uuid4()}"
        content = getattr(artifact, 'content', '') or ''
        mime = getattr(artifact, 'mime', 'text/plain') or 'text/plain'
        tags = list(getattr(artifact, 'tags', []) or [])
        attrs = dict(getattr(artifact, 'attrs', {}) or {})
        table = attrs.pop('_table', attrs.pop('table', 'default'))

        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO octopus_artifacts
                        (ref, table_name, content, mime, tags, attrs, size_bytes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ref) DO UPDATE SET
                        content = EXCLUDED.content,
                        updated_at = NOW()
                """, (ref, table, content, mime,
                       json.dumps(tags), json.dumps(attrs),
                       len(content.encode()) if isinstance(content, str) else len(content)))
        except Exception as e:
            logger.error("PostgreSQLAdapter.put error: %s", e)
            raise
        return ref

    async def get(self, ref: str) -> Any | None:
        """Получить артефакт по ref."""
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content, mime, tags, attrs FROM octopus_artifacts WHERE ref = %s",
                    (ref,)
                )
                row = cur.fetchone()
                if not row:
                    return None
                content, mime, tags, attrs = row
                return Artifact(
                    content=content, mime=mime,
                    tags=tags or [], provenance={}, attrs=attrs or {}
                )
        except Exception as e:
            logger.error("PostgreSQLAdapter.get error: %s", e)
            return None

    async def list(self, table: str = 'default', limit: int = 100) -> list:
        """Список записей из таблицы."""
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ref, content, mime, tags, attrs, created_at
                    FROM octopus_artifacts
                    WHERE table_name = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (table, limit))
                rows = cur.fetchall()
                return [
                    {'ref': r[0], 'content': r[1], 'mime': r[2],
                     'tags': r[3] or [], 'attrs': r[4] or {},
                     'created_at': r[5].isoformat() if r[5] else None}
                    for r in rows
                ]
        except Exception as e:
            logger.error("PostgreSQLAdapter.list error: %s", e)
            return []

    async def delete(self, ref: str) -> bool:
        """Удалить артефакт."""
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM octopus_artifacts WHERE ref = %s", (ref,))
                return cur.rowcount > 0
        except Exception as e:
            logger.error("PostgreSQLAdapter.delete error: %s", e)
            return False

    async def search(self, tags: list[str], owner: str | None = None, limit: int = 100) -> list:
        """Поиск по тегам."""
        try:
            from swarm.memory.types import RefMeta
            conn = self._connect()
            with conn.cursor() as cur:
                # Simple tag matching for now
                cur.execute("""
                    SELECT ref, table_name, tags FROM octopus_artifacts
                    WHERE tags ?| %s
                    ORDER BY created_at DESC LIMIT %s
                """, (tags, limit))
                rows = cur.fetchall()
                return [
                    RefMeta(ref=r[0], scheme='postgres', tags=r[2], block_type=r[1])
                    for r in rows
                ]
        except Exception as e:
            logger.error("PostgreSQLAdapter.search error: %s", e)
            return []

    def capabilities(self):
        from swarm.memory.types import Capabilities
        return Capabilities(
            schemes=frozenset({'postgres'}),
            supports_search=True,
            supports_delete=True,
            supports_promote=False
        )

    def stats(self) -> dict:
        """Статистика хранилища."""
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name, count(*), sum(size_bytes)
                    FROM octopus_artifacts
                    GROUP BY table_name ORDER BY count DESC
                """)
                rows = cur.fetchall()
                total = sum(r[1] for r in rows)
                return {
                    'backend': 'postgresql',
                    'total_records': total,
                    'tables': {r[0]: {'count': r[1], 'bytes': r[2] or 0} for r in rows},
                    'dsn': self._dsn.split('@')[-1] if '@' in self._dsn else self._dsn,
                }
        except Exception as e:
            return {'backend': 'postgresql', 'error': str(e)}

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
