"""Immortal Memory — hierarchical Hot/Warm/Cold storage with IPFS & Arweave.

Cold layer providers communicate via HTTP API:
- **IPFS** — Kubo RPC API (`/api/v0/add`, `/api/v0/cat`)
- **Arweave** — Gateway HTTP (`/tx`, data upload via Irys/Bundlr or direct)

Both are behind the ``ColdStorageProvider`` protocol, so new backends
(Filecoin, Storj, etc.) can be added without changing the manager.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


# ── Protocol ──────────────────────────────────────────────────────────────


class ColdStorageProvider(Protocol):
    """Интерфейс для cold-storage бэкендов."""

    async def store(self, content: bytes, tags: dict[str, str]) -> str:
        """Сохранить контент. Вернуть идентификатор (CID / TX ID)."""
        ...

    async def retrieve(self, identifier: str) -> bytes:
        """Получить контент по идентификатору."""
        ...

    async def exists(self, identifier: str) -> bool:
        """Проверить существование."""
        ...


# ── IPFS Provider ─────────────────────────────────────────────────────────


class IPFSProvider:
    """IPFS через Kubo RPC API (http://localhost:5001/api/v0/).

    Требуется запущенный IPFS-демон (Kubo) с включённым API.
    При отсутствии демона — симулирует (для тестов и offline).
    """

    def __init__(
        self,
        host: str = "http://localhost:5001",
        *,
        timeout: float = 30.0,
        gateway: str = "https://ipfs.io",
        simulate: bool = True,
    ) -> None:
        self.host = host.rstrip("/")
        self.gateway = gateway.rstrip("/")
        self._timeout = timeout
        self._simulate = simulate
        # Локальный кэш для симуляции
        self._sim_store: dict[str, bytes] = {}

    async def store(self, content: bytes, tags: dict[str, str]) -> str:
        if self._simulate:
            cid = f"bafy{hashlib.sha256(content).hexdigest()}"
            self._sim_store[cid] = content
            logger.info("IPFS store (simulated): %s (%d bytes)", cid, len(content))
            return cid

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self.host}/api/v0/add",
                    files={"file": ("data", content)},
                )
                resp.raise_for_status()
                data = resp.json()
                cid = data.get("Hash", "")
                logger.info("IPFS stored: %s (%d bytes)", cid, len(content))
                return cid
        except Exception as exc:
            logger.error("IPFS store failed: %s", exc)
            raise

    async def retrieve(self, identifier: str) -> bytes:
        full_cid = identifier if not identifier.startswith("ipfs:") else identifier[5:]

        if self._simulate:
            # Ищем по полному или частичному CID
            for key, val in self._sim_store.items():
                if key in (full_cid, identifier):
                    return val
            return b""

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self.host}/api/v0/cat",
                    params={"arg": full_cid},
                )
                resp.raise_for_status()
                return resp.content
        except Exception as exc:
            logger.error("IPFS retrieve failed for %s: %s", identifier, exc)
            raise

    async def exists(self, identifier: str) -> bool:
        if self._simulate:
            full_cid = identifier.removeprefix("ipfs:")
            return full_cid in self._sim_store or identifier in self._sim_store

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self.host}/api/v0/object/stat",
                    params={"arg": identifier},
                )
                return resp.status_code == 200
        except Exception:
            return False


# ── Arweave Provider ──────────────────────────────────────────────────────


class ArweaveProvider:
    """Arweave через HTTP Gateway.

    В реальной реализации upload идёт через Irys/Bundlr SDK.
    Retrieve — через любой gateway (`arweave.net`, `ar-io.net`).
    """

    def __init__(
        self,
        gateway: str = "https://arweave.net",
        *,
        key_file: str | None = None,
        timeout: float = 30.0,
        simulate: bool = True,
    ) -> None:
        self.gateway = gateway.rstrip("/")
        self.key_file = key_file
        self._timeout = timeout
        self._simulate = simulate
        self._sim_store: dict[str, bytes] = {}

    async def store(self, content: bytes, tags: dict[str, str]) -> str:
        if self._simulate:
            tx_id = hashlib.sha256(content).hexdigest()[:43]
            self._sim_store[tx_id] = content
            logger.info("Arweave store (simulated): %s (%d bytes)", tx_id, len(content))
            return tx_id

        # Реальный upload требует подпись транзакции ключом кошелька.
        # Для MVP используем Irys-like HTTP endpoint.
        raise NotImplementedError(
            "Real Arweave upload requires wallet key and Irys/Bundlr SDK. "
            "Use simulate=True for testing."
        )

    async def retrieve(self, identifier: str) -> bytes:
        tx_id = identifier.removeprefix("ar:")

        if self._simulate:
            return self._sim_store.get(tx_id, b"")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self.gateway}/{tx_id}")
                resp.raise_for_status()
                return resp.content
        except Exception as exc:
            logger.error("Arweave retrieve failed for %s: %s", identifier, exc)
            raise

    async def exists(self, identifier: str) -> bool:
        tx_id = identifier.removeprefix("ar:")

        if self._simulate:
            return tx_id in self._sim_store

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.head(f"{self.gateway}/{tx_id}")
                return resp.status_code == 200
        except Exception:
            return False


# ── Encrypted Wrapper ─────────────────────────────────────────────────────


class EncryptedStorage:
    """Шифрует данные перед отправкой в cold storage."""

    def __init__(self, provider: ColdStorageProvider, master_key: str) -> None:
        self.provider = provider
        self.master_key = master_key

    def _derive_key(self) -> bytes:
        """Derive 32-byte key from master_key (PBKDF2)."""
        import hashlib
        return hashlib.pbkdf2_hmac(
            "sha256",
            self.master_key.encode(),
            b"gemaxi-cold-salt",
            iterations=100_000,
        )

    def _encrypt(self, data: bytes) -> bytes:
        """AES-256-GCM encryption (or simulated prefix for tests)."""
        try:
            import os

            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = self._derive_key()
            nonce = os.urandom(12)
            ct = AESGCM(key).encrypt(nonce, data, None)
            return b"AESGCM:" + nonce + ct
        except ImportError:
            # Fallback: simple prefix (NOT secure, testing only)
            return b"ENC:" + data

    def _decrypt(self, data: bytes) -> bytes:
        if data.startswith(b"AESGCM:"):
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = self._derive_key()
            nonce = data[7:19]
            ct = data[19:]
            return AESGCM(key).decrypt(nonce, ct, None)
        if data.startswith(b"ENC:"):
            return data[4:]
        return data

    async def store(self, content: bytes, tags: dict[str, str]) -> str:
        encrypted = self._encrypt(content)
        return await self.provider.store(encrypted, tags)

    async def retrieve(self, identifier: str) -> bytes:
        encrypted = await self.provider.retrieve(identifier)
        return self._decrypt(encrypted)

    async def exists(self, identifier: str) -> bool:
        return await self.provider.exists(identifier)


# ── Archive Record ────────────────────────────────────────────────────────


@dataclass
class ArchiveRecord:
    """Запись об архивации в cold storage."""

    ref: str
    cold_id: str
    provider: str  # "ipfs" | "arweave"
    importance: float = 1.0
    archived_at: float = 0.0
    size_bytes: int = 0
    encrypted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "cold_id": self.cold_id,
            "provider": self.provider,
            "importance": self.importance,
            "archived_at": self.archived_at,
            "size_bytes": self.size_bytes,
            "encrypted": self.encrypted,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ArchiveRecord:
        return cls(
            ref=d.get("ref", ""),
            cold_id=d.get("cold_id", ""),
            provider=d.get("provider", ""),
            importance=float(d.get("importance", 1.0)),
            archived_at=float(d.get("archived_at", 0)),
            size_bytes=int(d.get("size_bytes", 0)),
            encrypted=bool(d.get("encrypted", False)),
        )


# ── ImmortalMemoryManager ────────────────────────────────────────────────

TABLE_ARCHIVE = "immortal_archive"


class ImmortalMemoryManager:
    """Оркестратор иерархического хранения: Hot → Warm → Cold.

    - **Hot**: VectorStore (для быстрого AI-recall)
    - **Warm**: MemoryRepository (структурированные метаданные, ссылки)
    - **Cold**: IPFS / Arweave (вечное хранение, 200+ лет)
    """

    def __init__(
        self,
        vector_store: Any,
        repository: Any,
        cold_storage: ColdStorageProvider | None = None,
        *,
        provider_name: str = "ipfs",
        encrypted: bool = False,
    ) -> None:
        self.vectors = vector_store
        self.repo = repository
        self.cold = cold_storage
        self._provider_name = provider_name
        self._encrypted = encrypted

    async def archive(
        self,
        ref: str,
        *,
        importance: float = 1.0,
        min_importance: float = 0.5,
    ) -> ArchiveRecord | None:
        """Отправить артефакт в cold storage.

        Возвращает ``ArchiveRecord`` при успехе, ``None`` если importance
        слишком низкая или cold storage недоступен.
        """
        if importance < min_importance:
            logger.debug("Skipping archive for %s: importance %.2f < %.2f", ref, importance, min_importance)
            return None

        if self.cold is None:
            logger.warning("No cold storage configured; cannot archive %s", ref)
            return None

        # Получаем артефакт из warm layer
        try:
            artifact = await self.repo._port.get(ref)
        except Exception as exc:
            logger.error("Cannot read %s from warm layer: %s", ref, exc)
            return None

        if artifact is None:
            return None

        content = artifact.content if isinstance(artifact.content, bytes) else artifact.content.encode("utf-8")
        tags_dict = {t: "true" for t in (artifact.tags or [])}
        tags_dict["importance"] = str(importance)
        tags_dict["original_ref"] = ref
        tags_dict["archived_at"] = str(time.time())

        # Загружаем в cold storage
        try:
            cold_id = await self.cold.store(content, tags_dict)
        except Exception as exc:
            logger.error("Cold storage failed for %s: %s", ref, exc)
            return None

        record = ArchiveRecord(
            ref=ref,
            cold_id=cold_id,
            provider=self._provider_name,
            importance=importance,
            archived_at=time.time(),
            size_bytes=len(content),
            encrypted=self._encrypted,
        )

        # Сохраняем запись об архивации в warm layer
        await self.repo.save(
            data=record.to_dict(),
            table=TABLE_ARCHIVE,
            tags=["immortal", "archived", f"provider:{self._provider_name}"],
            attrs={
                "cold_id": cold_id,
                "original_ref": ref,
                "importance": importance,
            },
        )

        logger.info("Archived %s → %s:%s (%.0f bytes)", ref, self._provider_name, cold_id, len(content))
        return record

    async def restore(self, cold_id: str) -> bytes | None:
        """Восстановить данные из cold storage по идентификатору."""
        if self.cold is None:
            return None
        try:
            return await self.cold.retrieve(cold_id)
        except Exception as exc:
            logger.error("Cold restore failed for %s: %s", cold_id, exc)
            return None

    async def check(self, cold_id: str) -> bool:
        """Проверить, жив ли артефакт в cold storage."""
        if self.cold is None:
            return False
        return await self.cold.exists(cold_id)

    async def archive_log(self, *, limit: int = 50) -> list[ArchiveRecord]:
        """Список архивированных записей."""
        rows = await self.repo.query(
            table=TABLE_ARCHIVE,
            order_by="attrs._ts:desc",
            limit=limit,
        )
        return [ArchiveRecord.from_dict(row.data) for row in rows]

    async def auto_archive(
        self,
        *,
        min_importance: float = 0.8,
        max_age_seconds: float = 86400 * 30,  # 30 дней
        limit: int = 100,
    ) -> list[ArchiveRecord]:
        """Автоматически архивировать «важные» записи.

        Критерии:
        - importance >= min_importance (из attrs)
        - Возраст >= max_age_seconds
        - Ещё не архивированы (нет cold_id)
        """
        all_rows = await self.repo.query(limit=limit * 3)
        archived: list[ArchiveRecord] = []
        now = time.time()

        for row in all_rows:
            # Пропускаем уже архивированные
            if row.attrs.get("cold_id"):
                continue
            # Пропускаем записи из таблицы архива
            if row.table == TABLE_ARCHIVE:
                continue

            imp = float(row.attrs.get("importance", 0))
            ts = float(row.attrs.get("_ts", now))
            age = now - ts

            if imp >= min_importance and age >= max_age_seconds:
                record = await self.archive(row.ref, importance=imp)
                if record:
                    archived.append(record)
                    if len(archived) >= limit:
                        break

        return archived

    def stats(self) -> dict:
        """Статистика для мониторинга."""
        return {
            "provider": self._provider_name,
            "cold_available": self.cold is not None,
            "encrypted": self._encrypted,
        }
