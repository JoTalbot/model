"""Multi-modal media processor: images, audio, documents.

Поддерживает:
- Импорт файлов с автоопределением типа
- Метаданные (размер, формат, хеш, длительность)
- OCR изображений (через Tesseract CLI, опционально)
- Транскрипция аудио (через Whisper-compatible API, опционально)
- Хранение через MemoryRepository

Все внешние зависимости (tesseract, ffprobe, whisper) опциональны —
без них модуль работает как хранилище с метаданными.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── MIME Detection ────────────────────────────────────────────────────────

_IMAGE_MIMES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/bmp", "image/tiff", "image/svg+xml",
})

_AUDIO_MIMES = frozenset({
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg",
    "audio/flac", "audio/aac", "audio/x-m4a", "audio/mp4",
    "audio/webm",
})

_DOCUMENT_MIMES = frozenset({
    "application/pdf", "text/plain", "text/markdown",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})


_EXT_IMAGE = {".webp", ".heic", ".heif", ".avif", ".jxl"}
_EXT_AUDIO = {".ogg", ".opus", ".flac", ".m4a", ".aac", ".wma"}

def detect_media_type(path: str | Path) -> str:
    """Определить тип медиа: 'image', 'audio', 'document', 'other'."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in _EXT_IMAGE:
        return "image"
    if ext in _EXT_AUDIO:
        return "audio"
    mime, _ = mimetypes.guess_type(str(path))
    if mime in _IMAGE_MIMES:
        return "image"
    if mime in _AUDIO_MIMES:
        return "audio"
    if mime in _DOCUMENT_MIMES:
        return "document"
    return "other"


def detect_mime(path: str | Path) -> str:
    """Определить MIME-тип файла."""
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


# ── Media Metadata ────────────────────────────────────────────────────────


@dataclass
class MediaMeta:
    """Метаданные медиафайла."""

    filename: str
    media_type: str  # 'image', 'audio', 'document', 'other'
    mime: str
    size_bytes: int
    sha256: str
    width: int | None = None   # для изображений
    height: int | None = None  # для изображений
    duration_seconds: float | None = None  # для аудио
    ocr_text: str | None = None
    transcript: str | None = None
    imported_at: float = 0.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "media_type": self.media_type,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "duration_seconds": self.duration_seconds,
            "ocr_text": self.ocr_text,
            "transcript": self.transcript,
            "imported_at": self.imported_at,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict) -> MediaMeta:
        return cls(
            filename=d.get("filename", ""),
            media_type=d.get("media_type", "other"),
            mime=d.get("mime", ""),
            size_bytes=int(d.get("size_bytes", 0)),
            sha256=d.get("sha256", ""),
            width=d.get("width"),
            height=d.get("height"),
            duration_seconds=d.get("duration_seconds"),
            ocr_text=d.get("ocr_text"),
            transcript=d.get("transcript"),
            imported_at=float(d.get("imported_at", 0)),
            tags=list(d.get("tags") or []),
        )


def compute_file_meta(path: str | Path) -> MediaMeta:
    """Вычислить метаданные файла (без OCR/транскрипции)."""
    p = Path(path)
    content = p.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    mime = detect_mime(p)
    media_type = detect_media_type(p)

    meta = MediaMeta(
        filename=p.name,
        media_type=media_type,
        mime=mime,
        size_bytes=len(content),
        sha256=sha,
        imported_at=time.time(),
    )

    # Попробуем извлечь размеры изображения (без Pillow)
    if media_type == "image":
        w, h = _image_dimensions(content, mime)
        meta.width = w
        meta.height = h

    # Попробуем извлечь длительность аудио (через ffprobe)
    if media_type == "audio":
        meta.duration_seconds = _audio_duration(str(p))

    return meta


def _image_dimensions(data: bytes, mime: str) -> tuple[int | None, int | None]:
    """Извлечь размеры изображения из заголовков (без Pillow)."""
    try:
        if mime == "image/png" and len(data) >= 24:
            # PNG IHDR: width at bytes 16-20, height at bytes 20-24
            w = int.from_bytes(data[16:20], "big")
            h = int.from_bytes(data[20:24], "big")
            return w, h
        if mime in ("image/jpeg", "image/jpg") and len(data) >= 2:
            return _jpeg_dimensions(data)
        if mime == "image/gif" and len(data) >= 10:
            w = int.from_bytes(data[6:8], "little")
            h = int.from_bytes(data[8:10], "little")
            return w, h
    except Exception:
        pass
    return None, None


def _jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Парсинг JPEG: ищем SOF0/SOF2 маркер."""
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker in (0xC0, 0xC2):  # SOF0, SOF2
            h = int.from_bytes(data[i + 5 : i + 7], "big")
            w = int.from_bytes(data[i + 7 : i + 9], "big")
            return w, h
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        i += 2 + length
    return None, None


def _audio_duration(path: str) -> float | None:
    """Получить длительность аудио через ffprobe (если установлен)."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


# ── OCR ───────────────────────────────────────────────────────────────────


def ocr_image(path: str | Path, *, lang: str = "rus+eng") -> str | None:
    """Распознать текст на изображении через Tesseract CLI.

    Возвращает None если Tesseract не установлен.
    """
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", lang],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            return text if text else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ── Whisper Transcription ─────────────────────────────────────────────────


async def transcribe_audio(
    path: str | Path,
    *,
    api_url: str = "http://127.0.0.1:8080/v1/audio/transcriptions",
    api_key: str | None = None,
    model: str = "whisper-1",
    language: str = "ru",
) -> str | None:
    """Транскрибировать аудио через OpenAI-compatible Whisper API.

    Совместимо с:
    - OpenAI Whisper API
    - faster-whisper-server
    - whisper.cpp server

    Возвращает None если API недоступен.
    """
    import httpx

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            with open(path, "rb") as f:
                resp = await client.post(
                    api_url,
                    headers=headers,
                    files={"file": (Path(path).name, f)},
                    data={"model": model, "language": language},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("text", "").strip() or None
    except Exception as exc:
        logger.warning("Whisper transcription failed for %s: %s", path, exc)
        return None


# ── MediaStore ────────────────────────────────────────────────────────────

TABLE_IMAGES = "media_images"
TABLE_AUDIO = "media_audio"
TABLE_DOCUMENTS = "media_documents"

_TYPE_TABLE = {
    "image": TABLE_IMAGES,
    "audio": TABLE_AUDIO,
    "document": TABLE_DOCUMENTS,
}


class MediaStore:
    """Хранилище медиафайлов поверх MemoryRepository."""

    def __init__(self, repository) -> None:
        self._repo = repository

    async def import_file(
        self,
        path: str | Path,
        *,
        tags: list[str] | None = None,
        ocr: bool = False,
        store_content: bool = True,
    ) -> tuple[str, MediaMeta]:
        """Импортировать файл. Возвращает (ref, meta).

        Parameters
        ----------
        path : путь к файлу
        tags : дополнительные теги
        ocr : запустить OCR для изображений
        store_content : сохранить содержимое в репо (иначе только метаданные)
        """
        p = Path(path)
        meta = compute_file_meta(p)
        meta.tags = list(tags or [])
        meta.tags.append(f"media:{meta.media_type}")

        if ocr and meta.media_type == "image":
            meta.ocr_text = ocr_image(p)

        data = meta.to_dict()
        if store_content:
            content = p.read_bytes()
            data["content_b64"] = base64.b64encode(content).decode("ascii")

        table = _TYPE_TABLE.get(meta.media_type, "media_other")
        ref = await self._repo.save(
            data=data,
            table=table,
            tags=meta.tags,
            attrs={
                "kind": "media",
                "media_type": meta.media_type,
                "mime": meta.mime,
                "sha256": meta.sha256,
                "size_bytes": meta.size_bytes,
            },
        )
        return ref, meta

    async def list_media(
        self,
        *,
        media_type: str | None = None,
        text: str | None = None,
        limit: int = 50,
    ) -> list[MediaMeta]:
        """Список медиафайлов."""
        table = _TYPE_TABLE.get(media_type) if media_type else None
        if table:
            rows = await self._repo.query(table=table, text=text, limit=limit)
        else:
            # Все типы
            rows = []
            for t in [TABLE_IMAGES, TABLE_AUDIO, TABLE_DOCUMENTS, "media_other"]:
                rows.extend(await self._repo.query(table=t, text=text, limit=limit))

        return [MediaMeta.from_dict(row.data) for row in rows[:limit]]

    async def find_by_hash(self, sha256: str) -> MediaMeta | None:
        """Найти медиа по SHA-256 хешу (дедупликация)."""
        for table in [TABLE_IMAGES, TABLE_AUDIO, TABLE_DOCUMENTS, "media_other"]:
            rows = await self._repo.query(
                table=table,
                attrs={"sha256": sha256},
                limit=1,
            )
            if rows:
                return MediaMeta.from_dict(rows[0].data)
        return None

    async def count(self, media_type: str | None = None) -> dict[str, int]:
        """Количество медиафайлов по типам."""
        result: dict[str, int] = {}
        for mtype, table in _TYPE_TABLE.items():
            if media_type and mtype != media_type:
                continue
            result[mtype] = await self._repo.count(table=table)
        return result

    async def search_ocr(self, query: str, *, limit: int = 20) -> list[MediaMeta]:
        """Поиск по OCR-тексту изображений."""
        rows = await self._repo.query(
            table=TABLE_IMAGES,
            text=query,
            limit=limit,
        )
        results = []
        for row in rows:
            meta = MediaMeta.from_dict(row.data)
            if meta.ocr_text and query.lower() in meta.ocr_text.lower():
                results.append(meta)
        return results
