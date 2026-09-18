"""Seed core AIOS database with realistic data for dashboard display (V3 schema)."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get(
    "OCTOPUS_DASH_DB", os.environ.get("AIOS_DB_PATH", "/app/data/aios.sqlite")
)


def init_schema(conn):
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL,
        agent_id TEXT,
        authority TEXT,
        risk_level TEXT,
        steps_data TEXT,
        current_step_index INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        error TEXT,
        metadata TEXT
    );
    CREATE TABLE IF NOT EXISTS memory_items (
        id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        tags TEXT,
        source TEXT,
        confidence REAL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        access_count INTEGER DEFAULT 0,
        metadata TEXT,
        owner_id TEXT
    );
    CREATE TABLE IF NOT EXISTS evolution_records (
        id TEXT PRIMARY KEY,
        evolution_type TEXT NOT NULL,
        proposed_at TEXT NOT NULL,
        status TEXT DEFAULT 'proposed'
    );
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        data TEXT,
        timestamp TEXT NOT NULL,
        agent_id TEXT,
        decision TEXT
    );
    """)
    conn.commit()


def seed(db_file=None):
    target_db = db_file or DB_PATH
    os.makedirs(os.path.dirname(target_db), exist_ok=True)
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row

    init_schema(conn)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as count FROM tasks")
    if cur.fetchone()["count"] > 0:
        print(f"Database {target_db} already contains tasks, skipping seed.")
        conn.close()
        return

    now = datetime.now(timezone.utc)

    # --- Seed tasks ---
    task_statuses = [
        ("completed", 45),
        ("running", 3),
        ("pending", 7),
        ("failed", 2),
    ]
    task_names = [
        "OLX ad collection cycle",
        "Android emulator screenshot capture",
        "Market price analysis for RTX 4090",
        "Telegram subscription notification",
        "Constitution rule validation",
        "Knowledge graph entity extraction",
        "Memory consolidation sweep",
        "Evolution proposal review",
        "ADB device lease allocation",
        "OLX analytics price distribution",
    ]
    task_descs = [
        "Collect and parse OLX ads for tracked queries",
        "Capture device screen and detect UI elements",
        "Analyze price trends for GPU listings",
        "Send alerts to subscribed Telegram users",
        "Validate task compliance against constitution",
        "Extract entities and relationships from memory",
        "Consolidate short-term memory into long-term storage",
        "Review and score evolution proposals",
        "Allocate Android emulator to automation profile",
        "Generate price distribution histogram for analytics",
    ]

    for status, count in task_statuses:
        for i in range(count):
            tid = uuid.uuid4().hex[:12]
            name = task_names[i % len(task_names)]
            desc = task_descs[i % len(task_descs)]
            created = (now - timedelta(hours=i * 3 + 1)).isoformat()
            started = (now - timedelta(hours=i * 3, minutes=5)).isoformat()
            completed = None
            if status == "completed":
                completed = (now - timedelta(hours=i * 3 - 30, minutes=15)).isoformat()
            elif status == "failed":
                completed = started
            agent = ["orch", "olx", "android", "tg", "policy"][i % 5]
            risk = ["low", "medium", "high"][i % 3]
            steps_data = json.dumps(
                [
                    {"name": "init", "status": "completed", "step_type": "tool"},
                    {
                        "name": "execute",
                        "status": status if status != "running" else "running",
                        "step_type": "tool",
                    },
                ]
            )
            cur.execute(
                """INSERT INTO tasks (id, name, description, status, agent_id, authority,
                    risk_level, steps_data, current_step_index, created_at, started_at,
                    completed_at, error, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tid,
                    name,
                    desc,
                    status,
                    agent,
                    "constitution",
                    risk,
                    steps_data,
                    1 if status == "running" else 0,
                    created,
                    started,
                    completed,
                    "Timeout waiting for emulator response"
                    if status == "failed"
                    else None,
                    json.dumps({"priority": i % 3, "query": "spot"}),
                ),
            )

    # --- Seed memory_items ---
    memory_contents = [
        ("operational", "OLX collector cycle completed: 305 ads parsed, 300 new"),
        ("operational", "Android emulator-5554 online, OLX app logged in"),
        ("operational", "Telegram bot received 3 new subscription requests"),
        ("operational", "Constitution validation: 1320 rules checked, 0 violations"),
        ("semantic", "OLX.ua price trends: RTX 4090 avg 23220 UAH, range 5-6990000"),
        ("semantic", "Kyiv apartment listings: median price 18500 UAH/m²"),
        ("semantic", "iPhone 15 Pro listings: 120 active, avg 42000 UAH"),
        ("episodic", "First successful ADB screenshot capture via dashboard API"),
        ("episodic", "OLX analytics dashboard loaded with 9229 ads"),
        ("procedural", "ADB device leasing: lease -> execute -> release workflow"),
        ("procedural", "OLX collection: query -> parse -> store -> notify cycle"),
        ("operational", "Knowledge graph: 67 constitutional articles indexed"),
    ]
    for i, (cat, content) in enumerate(memory_contents):
        mid = uuid.uuid4().hex[:12]
        created = (now - timedelta(hours=i + 1)).isoformat()
        updated = (now - timedelta(hours=i, minutes=30)).isoformat()
        tags = json.dumps(["auto", "dashboard", cat])
        cur.execute(
            """INSERT INTO memory_items (id, category, content, tags, source,
                confidence, created_at, updated_at, access_count, metadata, owner_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                cat,
                content,
                tags,
                "orchestrator",
                0.95,
                created,
                updated,
                i * 5,
                json.dumps({"importance": 0.8}),
                "aios",
            ),
        )

    # --- Seed evolution_records ---
    evolution_types = [
        "Improve OLX price prediction accuracy",
        "Add Android UI element detection to collector",
        "Optimize memory consolidation algorithm",
        "Add Telegram bot inline query support",
        "Integrate WebAssembly plugin system",
        "Add constitutional rule conflict resolver",
    ]

    for i, etype in enumerate(evolution_types):
        eid = str(uuid.uuid4())[:12]
        proposed_at = (now - timedelta(days=i + 1)).isoformat()
        cur.execute(
            """INSERT INTO evolution_records (id, evolution_type, proposed_at, status)
               VALUES (?, ?, ?, ?)""",
            (eid, etype, proposed_at, "proposed"),
        )

    # --- Seed audit_events ---
    audit_events = [
        ("task_created", "orchestrator", "Task created for OLX collection"),
        ("task_completed", "orchestrator", "Task completed: Android screenshot"),
        ("policy_validation", "policy", "Constitution rule validation passed"),
        ("memory_access", "memory", "Memory item retrieved for price analysis"),
        ("platform_event", "olx", "OLX collector cycle triggered"),
        ("platform_event", "android", "ADB device leased for automation"),
        ("approval_granted", "policy", "Evolution proposal approved for deployment"),
        ("approval_denied", "policy", "Low-scoring proposal rejected"),
    ]

    for i, (etype, agent, detail) in enumerate(audit_events):
        aid = str(uuid.uuid4())[:12]
        ts = (now - timedelta(hours=i + 1)).isoformat()
        cur.execute(
            """INSERT INTO audit_events (id, event_type, data, timestamp,
                agent_id, decision)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                aid,
                etype,
                json.dumps({"detail": detail, "task_id": uuid.uuid4().hex[:12]}),
                ts,
                agent,
                "allow",
            ),
        )

    conn.commit()
    conn.close()
    print(
        f"Seeded DB at {target_db}: tasks, memory_items, evolution_records, audit_events"
    )


if __name__ == "__main__":
    seed()
