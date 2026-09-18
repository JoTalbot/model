"""
Octopus Universal Memory PWA API (Instruction #54)
Backend API for storage, search, offline sync, and WebDAV compatibility layer.
"""
import os
import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

DB_PATH = os.environ.get("OCTOPUS_MEMORY_DB",
    "/var/lib/octopus/memory_skill.db")

def init_db(db_path: str = DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory_items (
        id TEXT PRIMARY KEY,
        item_type TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        tags TEXT,
        sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL,
        modified_at TEXT NOT NULL,
        synced INTEGER DEFAULT 1
    )
    """)
    conn.commit()
    conn.close()

def save_memory_item(
    item_id: str,
    item_type: str,
    title: str,
    content: str,
    tags: List[str] = None,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    tags_str = ",".join(tags or [])
    content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO memory_items (id, item_type, title, content, tags, sha256, created_at, modified_at, synced)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    ON CONFLICT(id) DO UPDATE SET
        title=excluded.title,
        content=excluded.content,
        tags=excluded.tags,
        sha256=excluded.sha256,
        modified_at=excluded.modified_at,
        synced=1
    """, (item_id, item_type, title, content, tags_str, content_sha, now, now))
    conn.commit()
    conn.close()

    return {
        "id": item_id,
        "item_type": item_type,
        "title": title,
        "content_length": len(content),
        "sha256": content_sha,
        "modified_at": now
    }

def search_memory(query: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    q_pattern = f"%{query.strip()}%"
    cur.execute("""
    SELECT id, item_type, title, content, tags, sha256, created_at, modified_at
    FROM memory_items
    WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
    ORDER BY modified_at DESC LIMIT 50
    """, (q_pattern, q_pattern, q_pattern))
    rows = cur.fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "item_type": r[1],
            "title": r[2],
            "content": r[3],
            "tags": r[4].split(",") if r[4] else [],
            "sha256": r[5],
            "created_at": r[6],
            "modified_at": r[7]
        })
    return results

if __name__ == "__main__":
    init_db()
    save_memory_item("note-001", "note", "Инструкция по Памяти", "Октопус использует бессмертную память и PWA файлообменник.", ["память", "инструкция"])
    print("Search results:", search_memory("бессмертную"))
