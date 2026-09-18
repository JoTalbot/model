"""Durable per-chat LLM generation scheduler.

Polling only persists an inbound job and immediately returns to ``getUpdates``.
Each chat has one sequential worker, while different chats can generate in
parallel. Worker leases are renewed while generation runs; expired jobs are
replayed safely because the outbound queue owns the final update-id dedup key.
Jobs that exhaust their bounded attempts enter an operator-visible dead letter
state instead of being silently discarded.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from swarm.tgbot.crypto_store import QueueCipher
from swarm.tgbot.paths import credential_path, state_path

GenerationHandler = Callable[[dict], bool]


class QueueDrainingError(RuntimeError):
    """Raised when polling tries to enqueue after graceful drain started."""


class TelegramGenerationQueue:
    def __init__(
        self,
        handler: GenerationHandler,
        db_path: str | Path | None = None,
        *,
        max_attempts: int = 2,
        lease_seconds: float | None = None,
    ) -> None:
        self.handler = handler
        self.db_path = Path(
            db_path
            or os.environ.get("TELEGRAM_GENERATION_DB", "")
            or state_path("telegram_generation.sqlite3")
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        key_path = (
            self.db_path.with_suffix(self.db_path.suffix + ".key")
            if db_path is not None
            else Path(__file__).resolve().parents[1]
            / "data"
            / "credentials"
            / "telegram_queue.key"
        )
        self._cipher = QueueCipher(
            os.environ.get("TELEGRAM_QUEUE_KEY_FILE", "")
            or credential_path("telegram_queue_key", key_path)
        )
        self.max_attempts = max(1, int(max_attempts))
        self.lease_seconds = max(
            2.0,
            float(
                lease_seconds
                if lease_seconds is not None
                else os.environ.get("TELEGRAM_GENERATION_LEASE_SECONDS", "120")
            ),
        )
        self._worker_id = f"{os.getpid()}:{uuid.uuid4().hex}"
        self._stop = threading.Event()
        self._accepting = True
        self._workers: dict[int, threading.Thread] = {}
        self._workers_lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        for path in (
            self.db_path,
            Path(str(self.db_path) + "-wal"),
            Path(str(self.db_path) + "-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_generation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT NOT NULL UNIQUE,
                    chat_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    encrypted INTEGER NOT NULL DEFAULT 1,
                    source_message_id INTEGER,
                    voice_reply INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_class TEXT NOT NULL DEFAULT '',
                    worker_pid INTEGER,
                    worker_id TEXT,
                    lease_until REAL,
                    lease_epoch INTEGER NOT NULL DEFAULT 0,
                    last_heartbeat_at REAL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                )
                """
            )
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(telegram_generation)")
            }
            if "worker_id" not in columns:
                db.execute("ALTER TABLE telegram_generation ADD COLUMN worker_id TEXT")
            if "last_heartbeat_at" not in columns:
                db.execute(
                    "ALTER TABLE telegram_generation ADD COLUMN last_heartbeat_at REAL"
                )
            if "lease_epoch" not in columns:
                db.execute(
                    "ALTER TABLE telegram_generation "
                    "ADD COLUMN lease_epoch INTEGER NOT NULL DEFAULT 0"
                )
            # Previous releases used ``failed`` for exhausted bounded retries.
            # Preserve those rows as explicit operator-visible dead letters.
            db.execute(
                "UPDATE telegram_generation SET status='dead_letter' WHERE status='failed'"
            )
            self._reap_expired_leases(db=db)
            now = time.time()
            retention_days = max(
                1, int(os.environ.get("TELEGRAM_GENERATION_RETENTION_DAYS", "14"))
            )
            dead_letter_days = max(
                retention_days,
                int(os.environ.get("TELEGRAM_DEAD_LETTER_RETENTION_DAYS", "30")),
            )
            db.execute(
                "DELETE FROM telegram_generation WHERE created_at < ? AND status IN ('completed','failed')",
                (now - retention_days * 86400,),
            )
            db.execute(
                "DELETE FROM telegram_generation WHERE created_at < ? AND status='dead_letter'",
                (now - dead_letter_days * 86400,),
            )

    def _reap_expired_leases(self, *, db: sqlite3.Connection | None = None) -> int:
        owned = db is None
        connection = db or self._connect()
        try:
            now = time.time()
            result = connection.execute(
                """
                UPDATE telegram_generation
                SET status='pending', worker_pid=NULL, worker_id=NULL,
                    lease_until=NULL, last_heartbeat_at=NULL,
                    error_class='lease_expired'
                WHERE status='generating' AND COALESCE(lease_until, 0) < ?
                """,
                (now,),
            )
            if owned:
                connection.commit()
            return int(result.rowcount)
        finally:
            if owned:
                connection.close()

    def start(self) -> None:
        self._stop.clear()
        self._accepting = True
        self._reap_expired_leases()
        with self._connect() as db:
            chats = [
                int(row[0])
                for row in db.execute(
                    "SELECT DISTINCT chat_id FROM telegram_generation WHERE status='pending'"
                )
            ]
        for chat_id in chats:
            self._ensure_worker(chat_id)

    def begin_drain(self) -> None:
        """Reject new jobs while allowing already durable jobs to finish."""
        self._accepting = False

    def stop(self, timeout: float = 3.0, *, drain: bool = False) -> bool:
        if drain:
            self.begin_drain()
            deadline = time.monotonic() + max(0.0, timeout)
            while time.monotonic() < deadline:
                with self._connect() as db:
                    remaining = int(
                        db.execute(
                            "SELECT COUNT(*) FROM telegram_generation "
                            "WHERE status IN ('pending','generating')"
                        ).fetchone()[0]
                    )
                if remaining == 0:
                    break
                time.sleep(0.05)
        self._stop.set()
        with self._workers_lock:
            workers = list(self._workers.values())
        deadline = time.monotonic() + max(0.0, timeout)
        for worker in workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        return all(not worker.is_alive() for worker in workers)

    def enqueue(
        self,
        *,
        dedup_key: str,
        chat_id: int,
        text: str,
        source_message_id: int | None = None,
        voice_reply: bool = False,
    ) -> bool:
        if not self._accepting:
            raise QueueDrainingError("generation queue is draining")
        if not dedup_key or not text:
            raise ValueError("dedup_key and text are required")
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO telegram_generation (
                    dedup_key, chat_id, text, encrypted, source_message_id,
                    voice_reply, status, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, 'pending', ?)
                """,
                (
                    dedup_key,
                    int(chat_id),
                    self._cipher.encrypt(text),
                    source_message_id,
                    1 if voice_reply else 0,
                    time.time(),
                ),
            )
            inserted = cursor.rowcount == 1
        if inserted:
            self._ensure_worker(int(chat_id))
        return inserted

    def seen(self, dedup_key: str) -> bool:
        return self.get(dedup_key) is not None

    def get(self, dedup_key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM telegram_generation WHERE dedup_key=?", (dedup_key,)
            ).fetchone()
        return dict(row) if row else None

    def wait(self, dedup_key: str, timeout: float = 10.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = self.get(dedup_key)
            if row and row["status"] not in ("pending", "generating"):
                return row
            time.sleep(0.02)
        return self.get(dedup_key)

    def list_dead_letters(self, limit: int = 20) -> list[dict]:
        """Return operator-safe metadata; encrypted message content is omitted."""
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, dedup_key, chat_id, status, attempts, error_class,
                       created_at, started_at, finished_at
                FROM telegram_generation
                WHERE status='dead_letter'
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(100, int(limit))),),
            ).fetchall()
        return [dict(row) for row in rows]

    def requeue_dead_letter(self, item_id: int) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT chat_id FROM telegram_generation WHERE id=? AND status='dead_letter'",
                (int(item_id),),
            ).fetchone()
            if not row:
                db.commit()
                return False
            changed = db.execute(
                """
                UPDATE telegram_generation
                SET status='pending', attempts=0, error_class='', started_at=NULL,
                    finished_at=NULL, worker_pid=NULL, worker_id=NULL,
                    lease_until=NULL, last_heartbeat_at=NULL
                WHERE id=? AND status='dead_letter'
                """,
                (int(item_id),),
            ).rowcount
            db.commit()
        if changed:
            self._ensure_worker(int(row["chat_id"]))
        return changed == 1

    def _ensure_worker(self, chat_id: int) -> None:
        with self._workers_lock:
            current = self._workers.get(chat_id)
            if current and current.is_alive():
                return
            worker = threading.Thread(
                target=self._chat_worker,
                args=(chat_id,),
                name=f"telegram-generation-{chat_id}",
                daemon=True,
            )
            self._workers[chat_id] = worker
            worker.start()

    def _claim(self, chat_id: int) -> sqlite3.Row | None:
        self._reap_expired_leases()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT id FROM telegram_generation AS candidate
                WHERE candidate.chat_id=? AND candidate.status='pending'
                  AND NOT EXISTS (
                      SELECT 1 FROM telegram_generation AS active
                      WHERE active.chat_id=candidate.chat_id AND active.status='generating'
                  )
                ORDER BY candidate.id LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
            if not row:
                db.commit()
                return None
            now = time.time()
            changed = db.execute(
                """
                UPDATE telegram_generation
                SET status='generating', attempts=attempts+1, lease_epoch=lease_epoch+1,
                    started_at=?, finished_at=NULL, worker_pid=?, worker_id=?,
                    lease_until=?, last_heartbeat_at=?
                WHERE id=? AND status='pending'
                """,
                (
                    now,
                    os.getpid(),
                    self._worker_id,
                    now + self.lease_seconds,
                    now,
                    row["id"],
                ),
            ).rowcount
            claimed = (
                db.execute(
                    "SELECT * FROM telegram_generation WHERE id=?", (row["id"],)
                ).fetchone()
                if changed == 1
                else None
            )
            db.commit()
            return claimed

    def _renew_lease(
        self, item_id: int, lease_epoch: int, stop: threading.Event
    ) -> None:
        interval = max(1.0, min(30.0, self.lease_seconds / 3.0))
        while not stop.wait(interval):
            now = time.time()
            with self._connect() as db:
                changed = db.execute(
                    """
                    UPDATE telegram_generation
                    SET lease_until=?, last_heartbeat_at=?
                    WHERE id=? AND status='generating' AND worker_id=?
                      AND lease_epoch=?
                    """,
                    (
                        now + self.lease_seconds,
                        now,
                        item_id,
                        self._worker_id,
                        lease_epoch,
                    ),
                ).rowcount
            if changed != 1:
                return

    def _finish(
        self,
        item_id: int,
        lease_epoch: int,
        *,
        status: str,
        error_class: str = "",
    ) -> bool:
        with self._connect() as db:
            changed = db.execute(
                """
                UPDATE telegram_generation
                SET status=?, error_class=?, worker_pid=NULL, worker_id=NULL,
                    lease_until=NULL, last_heartbeat_at=NULL, finished_at=?
                WHERE id=? AND status='generating' AND worker_id=?
                  AND lease_epoch=?
                """,
                (
                    status,
                    error_class,
                    time.time(),
                    item_id,
                    self._worker_id,
                    lease_epoch,
                ),
            ).rowcount
        return changed == 1

    def _retry_or_dead_letter(self, row: sqlite3.Row, error_class: str) -> bool:
        status = (
            "pending" if int(row["attempts"]) < self.max_attempts else "dead_letter"
        )
        with self._connect() as db:
            changed = db.execute(
                """
                UPDATE telegram_generation
                SET status=?, error_class=?, worker_pid=NULL, worker_id=NULL,
                    lease_until=NULL, last_heartbeat_at=NULL,
                    finished_at=CASE WHEN ?='dead_letter' THEN ? ELSE NULL END
                WHERE id=? AND status='generating' AND worker_id=?
                  AND lease_epoch=?
                """,
                (
                    status,
                    error_class,
                    status,
                    time.time(),
                    row["id"],
                    self._worker_id,
                    row["lease_epoch"],
                ),
            ).rowcount
        return changed == 1

    def _chat_worker(self, chat_id: int) -> None:
        try:
            while not self._stop.is_set():
                row = self._claim(chat_id)
                if row is None:
                    return
                heartbeat_stop = threading.Event()
                heartbeat = threading.Thread(
                    target=self._renew_lease,
                    args=(int(row["id"]), int(row["lease_epoch"]), heartbeat_stop),
                    name=f"telegram-generation-heartbeat-{row['id']}",
                    daemon=True,
                )
                heartbeat.start()
                job = dict(row)
                try:
                    job["text"] = self._cipher.decrypt(
                        str(row["text"]), encrypted=bool(row["encrypted"])
                    )
                    completed = bool(self.handler(job))
                    if completed:
                        self._finish(
                            int(row["id"]),
                            int(row["lease_epoch"]),
                            status="completed",
                        )
                    else:
                        self._retry_or_dead_letter(row, "handler_incomplete")
                except Exception as exc:
                    self._retry_or_dead_letter(row, type(exc).__name__)
                    print(
                        f"  [LLM] generation job failed ({row['dedup_key']}): "
                        f"{type(exc).__name__}"
                    )
                finally:
                    heartbeat_stop.set()
                    heartbeat.join(timeout=1.0)
        finally:
            with self._workers_lock:
                current = self._workers.get(chat_id)
                if current is threading.current_thread():
                    self._workers.pop(chat_id, None)
            # Close the enqueue/worker-exit race.
            if not self._stop.is_set():
                with self._connect() as db:
                    pending = db.execute(
                        "SELECT 1 FROM telegram_generation WHERE chat_id=? AND status='pending' LIMIT 1",
                        (chat_id,),
                    ).fetchone()
                if pending:
                    self._ensure_worker(chat_id)
