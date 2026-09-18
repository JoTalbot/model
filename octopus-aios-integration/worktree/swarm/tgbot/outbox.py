"""Persistent at-most-once Telegram outbound queue.

Telegram Bot API has no idempotency key.  Retrying a ``sendMessage`` after a
read timeout can therefore create duplicates: Telegram may have accepted the
first request even though the client never received its response.  This queue
marks an item as ``sending`` *before* the network call and never automatically
retries an ambiguous failure.  A process restart converts stale ``sending``
rows to ``failed_unknown`` rather than delivering them again.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from swarm.tgbot.crypto_store import QueueCipher
from swarm.tgbot.paths import credential_path, state_path

OnSent = Callable[[dict], None]


class TelegramOutbox:
    def __init__(self, api: Any, db_path: str | Path | None = None) -> None:
        self.api = api
        self.db_path = Path(
            db_path
            or os.environ.get("TELEGRAM_OUTBOX_DB", "")
            or state_path("telegram_outbox.sqlite3")
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        default_key = (
            self.db_path.with_suffix(self.db_path.suffix + ".key")
            if db_path is not None
            else Path(__file__).resolve().parents[1]
            / "data"
            / "credentials"
            / "telegram_queue.key"
        )
        self._cipher = QueueCipher(
            os.environ.get("TELEGRAM_QUEUE_KEY_FILE", "")
            or credential_path("telegram_queue_key", default_key)
        )
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._accepting = True
        self._callbacks: dict[int, OnSent] = {}
        self._callbacks_lock = threading.Lock()
        self._worker_id = f"{os.getpid()}:{uuid.uuid4().hex}"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        for path in (
            self.db_path,
            Path(str(self.db_path) + "-wal"),
            Path(str(self.db_path) + "-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT NOT NULL UNIQUE,
                    chat_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    encrypted INTEGER NOT NULL DEFAULT 0,
                    parse_mode TEXT NOT NULL DEFAULT '',
                    reply_markup_json TEXT,
                    options_json TEXT,
                    generation_sec REAL NOT NULL DEFAULT 0,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    telegram_message_id INTEGER,
                    error_class TEXT NOT NULL DEFAULT '',
                    worker_pid INTEGER,
                    worker_id TEXT,
                    lease_until REAL,
                    lease_epoch INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                )
                """
            )
            # Lightweight migration for databases created before worker leases.
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(telegram_outbox)")
            }
            if "worker_pid" not in columns:
                db.execute("ALTER TABLE telegram_outbox ADD COLUMN worker_pid INTEGER")
            if "lease_until" not in columns:
                db.execute("ALTER TABLE telegram_outbox ADD COLUMN lease_until REAL")
            if "worker_id" not in columns:
                db.execute("ALTER TABLE telegram_outbox ADD COLUMN worker_id TEXT")
            if "lease_epoch" not in columns:
                db.execute(
                    "ALTER TABLE telegram_outbox "
                    "ADD COLUMN lease_epoch INTEGER NOT NULL DEFAULT 0"
                )
            if "encrypted" not in columns:
                db.execute(
                    "ALTER TABLE telegram_outbox ADD COLUMN encrypted INTEGER NOT NULL DEFAULT 0"
                )
            if "options_json" not in columns:
                db.execute("ALTER TABLE telegram_outbox ADD COLUMN options_json TEXT")

            # Encrypt legacy plaintext payloads in place before normal queue use.
            # This makes the migration one-way while keeping all metadata intact.
            legacy_rows = db.execute(
                "SELECT id, text FROM telegram_outbox WHERE encrypted=0"
            ).fetchall()
            for legacy in legacy_rows:
                db.execute(
                    "UPDATE telegram_outbox SET text=?, encrypted=1 WHERE id=? AND encrypted=0",
                    (self._cipher.encrypt(str(legacy["text"])), int(legacy["id"])),
                )

            # A second process (for example the canary) must not invalidate the
            # bot's active send. Fail closed only when the owner process is gone
            # or its bounded network lease has expired.
            now = time.time()
            for row in db.execute(
                "SELECT id, worker_pid, lease_until FROM telegram_outbox WHERE status='sending'"
            ).fetchall():
                pid = int(row["worker_pid"] or 0)
                lease_until = float(row["lease_until"] or 0)
                owner_alive = pid > 0 and Path(f"/proc/{pid}").exists()
                if not owner_alive or lease_until < now:
                    db.execute(
                        """
                        UPDATE telegram_outbox
                        SET status='failed_unknown', error_class='process_interrupted',
                            finished_at=?, worker_pid=NULL, worker_id=NULL,
                            lease_until=NULL, lease_epoch=lease_epoch+1
                        WHERE id=? AND status='sending'
                        """,
                        (now, row["id"]),
                    )
            retention_days = max(
                1, int(os.environ.get("TELEGRAM_OUTBOX_RETENTION_DAYS", "30"))
            )
            db.execute(
                "DELETE FROM telegram_outbox WHERE created_at < ? AND status IN ('sent','failed','failed_unknown','resend_queued')",
                (time.time() - retention_days * 86400,),
            )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._accepting = True
        self._thread = threading.Thread(
            target=self._worker, name="telegram-outbox", daemon=True
        )
        self._thread.start()

    def begin_drain(self) -> None:
        self._accepting = False
        self._wake.set()

    def stop(self, timeout: float = 3.0, *, drain: bool = False) -> bool:
        if drain:
            self.begin_drain()
            deadline = time.monotonic() + max(0.0, timeout)
            while time.monotonic() < deadline:
                with self._connect() as db:
                    remaining = int(
                        db.execute(
                            "SELECT COUNT(*) FROM telegram_outbox "
                            "WHERE status IN ('pending','sending')"
                        ).fetchone()[0]
                    )
                if remaining == 0:
                    break
                self._wake.set()
                time.sleep(0.05)
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=max(0.0, timeout))
            return not self._thread.is_alive()
        return True

    def seen(self, dedup_key: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM telegram_outbox WHERE dedup_key=? LIMIT 1", (dedup_key,)
            ).fetchone()
        return row is not None

    def enqueue(
        self,
        *,
        dedup_key: str,
        chat_id: int,
        text: str,
        parse_mode: str = "",
        reply_markup: dict | None = None,
        generation_sec: float = 0.0,
        provider: str = "",
        model: str = "",
        on_sent: OnSent | None = None,
        disable_notification: bool = False,
        reply_to_message_id: int | None = None,
        metric_event: str = "telegram_send",
    ) -> bool:
        """Persist one message. Return ``False`` when its dedup key already exists."""
        if not self._accepting:
            raise RuntimeError("Telegram outbox is draining")
        if not dedup_key or not text:
            raise ValueError("dedup_key and text are required")
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO telegram_outbox (
                    dedup_key, chat_id, text, encrypted, parse_mode, reply_markup_json,
                    options_json, generation_sec, provider, model, status, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    dedup_key,
                    int(chat_id),
                    self._cipher.encrypt(text),
                    parse_mode,
                    json.dumps(reply_markup, ensure_ascii=False)
                    if reply_markup
                    else None,
                    json.dumps(
                        {
                            "disable_notification": bool(disable_notification),
                            "reply_to_message_id": reply_to_message_id,
                            "metric_event": metric_event
                            if metric_event
                            else "telegram_send",
                        },
                        separators=(",", ":"),
                    ),
                    max(0.0, float(generation_sec)),
                    provider,
                    model,
                    time.time(),
                ),
            )
            inserted = cursor.rowcount == 1
            item_id = int(cursor.lastrowid) if inserted else 0
        if inserted and on_sent:
            with self._callbacks_lock:
                self._callbacks[item_id] = on_sent
        if inserted:
            self._wake.set()
        return inserted

    def get(self, dedup_key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM telegram_outbox WHERE dedup_key=?", (dedup_key,)
            ).fetchone()
        return dict(row) if row else None

    def wait(self, dedup_key: str, timeout: float = 10.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = self.get(dedup_key)
            if row and row["status"] not in ("pending", "sending"):
                return row
            time.sleep(0.02)
        return self.get(dedup_key)

    def list_uncertain(self, limit: int = 20) -> list[dict]:
        """Return metadata only; message contents remain encrypted."""
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, dedup_key, chat_id, status, attempts, error_class, created_at, finished_at
                FROM telegram_outbox
                WHERE status='failed_unknown'
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def manual_resend(self, item_id: int, *, dedup_key: str | None = None) -> bool:
        """Atomically replay one uncertain row under a new deduplication key."""
        key = dedup_key or f"manual-resend:{int(item_id)}:{time.time_ns()}"
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM telegram_outbox WHERE id=? AND status='failed_unknown'",
                (int(item_id),),
            ).fetchone()
            if not row:
                db.commit()
                return False
            inserted = db.execute(
                """
                INSERT OR IGNORE INTO telegram_outbox (
                    dedup_key, chat_id, text, encrypted, parse_mode, reply_markup_json,
                    options_json, generation_sec, provider, model, status, created_at
                )
                SELECT ?, chat_id, text, encrypted, parse_mode, reply_markup_json,
                       options_json, generation_sec, provider, model, 'pending', ?
                FROM telegram_outbox WHERE id=? AND status='failed_unknown'
                """,
                (key, time.time(), int(item_id)),
            ).rowcount
            if inserted == 1:
                db.execute(
                    "UPDATE telegram_outbox SET status='resend_queued', finished_at=? "
                    "WHERE id=? AND status='failed_unknown'",
                    (time.time(), int(item_id)),
                )
            db.commit()
        if inserted == 1:
            self._wake.set()
            return True
        return False

    def _claim_next(self) -> sqlite3.Row | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT id FROM telegram_outbox AS candidate
                WHERE candidate.status='pending'
                  AND NOT EXISTS (
                      SELECT 1 FROM telegram_outbox AS active WHERE active.status='sending'
                  )
                ORDER BY candidate.id LIMIT 1
                """
            ).fetchone()
            if not row:
                db.commit()
                return None
            now = time.time()
            updated = db.execute(
                """
                UPDATE telegram_outbox
                SET status='sending', attempts=attempts+1,
                    lease_epoch=lease_epoch+1, started_at=?, worker_pid=?,
                    worker_id=?, lease_until=?
                WHERE id=? AND status='pending'
                """,
                (
                    now,
                    os.getpid(),
                    self._worker_id,
                    now + 60,
                    row["id"],
                ),
            ).rowcount
            claimed = (
                db.execute(
                    "SELECT * FROM telegram_outbox WHERE id=?", (row["id"],)
                ).fetchone()
                if updated == 1
                else None
            )
            db.commit()
            return claimed

    def _finish(
        self,
        item_id: int,
        lease_epoch: int,
        *,
        status: str,
        telegram_message_id: int | None = None,
        error_class: str = "",
    ) -> bool:
        with self._connect() as db:
            changed = db.execute(
                """
                UPDATE telegram_outbox
                SET status=?, telegram_message_id=?, error_class=?, finished_at=?,
                    worker_pid=NULL, worker_id=NULL, lease_until=NULL
                WHERE id=? AND status='sending' AND worker_id=?
                  AND lease_epoch=?
                """,
                (
                    status,
                    telegram_message_id,
                    error_class,
                    time.time(),
                    item_id,
                    self._worker_id,
                    lease_epoch,
                ),
            ).rowcount
        return changed == 1

    def _record_metric(self, event: dict) -> None:
        try:
            from swarm.tgbot.metrics import record_telegram_event

            record_telegram_event(event)
        except Exception:
            pass

    def _worker(self) -> None:
        while not self._stop.is_set():
            row = self._claim_next()
            if row is None:
                self._wake.clear()
                self._wake.wait(timeout=1.0)
                continue

            send_started = time.monotonic()
            status = "failed_unknown"
            error_class = ""
            telegram_message_id = None
            result: dict = {}
            options: dict = {}
            network_started = False
            try:
                reply_markup = (
                    json.loads(row["reply_markup_json"])
                    if row["reply_markup_json"]
                    else None
                )
                options = json.loads(row["options_json"]) if row["options_json"] else {}
                text = self._cipher.decrypt(
                    str(row["text"]), encrypted=bool(row["encrypted"])
                )
                send_kwargs = {
                    "parse_mode": str(row["parse_mode"]),
                    "reply_markup": reply_markup,
                }
                if options.get("disable_notification"):
                    send_kwargs["disable_notification"] = True
                if options.get("reply_to_message_id"):
                    send_kwargs["reply_to_message_id"] = int(
                        options["reply_to_message_id"]
                    )
                network_started = True
                result = self.api.send_message(int(row["chat_id"]), text, **send_kwargs)
                telegram_message_id = result.get("result", {}).get("message_id")
                status = "sent"
            except Exception as exc:
                # Only transport failures after request start are ambiguous. A
                # complete Bot API rejection or local decode error is definite.
                error_class = type(exc).__name__
                http_status = getattr(
                    getattr(exc, "response", None), "status_code", None
                )
                definite_http_rejection = bool(
                    error_class == "HTTPError"
                    and http_status
                    and int(http_status) < 500
                )
                if (
                    not network_started
                    or error_class == "TelegramAPIError"
                    or definite_http_rejection
                ):
                    status = "failed"
            send_sec = time.monotonic() - send_started
            finalized = self._finish(
                int(row["id"]),
                int(row["lease_epoch"]),
                status=status,
                telegram_message_id=telegram_message_id,
                error_class=error_class,
            )
            if not finalized:
                # A newer lease epoch invalidated this worker. Never overwrite
                # the operator-visible ambiguous state or invoke callbacks.
                status = "stale_fenced"
                error_class = "StaleLeaseEpoch"
            total_sec = float(row["generation_sec"]) + send_sec
            event = {
                "event": str(options.get("metric_event") or "telegram_send"),
                "status": status,
                "dedup_key": row["dedup_key"],
                "provider": row["provider"],
                "model": row["model"],
                "gen_sec": round(float(row["generation_sec"]), 3),
                "send_sec": round(send_sec, 3),
                "total_sec": round(total_sec, 3),
                "attempts": int(row["attempts"]),
                "error_class": error_class,
                "timestamp": time.time(),
            }
            self._record_metric(event)
            if status == "sent":
                print(
                    f"  -> LLM sent (provider={row['provider'] or 'unknown'}, "
                    f"model={row['model'] or 'unknown'}, gen={float(row['generation_sec']):.2f}s, "
                    f"send={send_sec:.2f}s, total={total_sec:.2f}s, status=sent)"
                )
                callback = None
                with self._callbacks_lock:
                    callback = self._callbacks.pop(int(row["id"]), None)
                if callback:
                    try:
                        callback(result)
                    except Exception as exc:
                        print(
                            f"  [VOICE] post-send callback failed: {type(exc).__name__}"
                        )
            else:
                with self._callbacks_lock:
                    self._callbacks.pop(int(row["id"]), None)
                print(
                    f"  [ERR] LLM send status={status}, error={error_class}, "
                    f"gen={float(row['generation_sec']):.2f}s, send={send_sec:.2f}s, total={total_sec:.2f}s"
                )
