"""Тесты для swarm.media.processor — мультимодальная обработка."""

import base64
import struct
from pathlib import Path

import pytest

from swarm.media.processor import (
    MediaMeta,
    MediaStore,
    _image_dimensions,
    compute_file_meta,
    detect_media_type,
    detect_mime,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_png(tmp_path: Path, w: int = 100, h: int = 80) -> Path:
    """Создать минимальный PNG файл."""
    p = tmp_path / "test.png"
    # PNG header + IHDR chunk
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    import zlib
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    # IEND
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    p.write_bytes(header + ihdr + iend)
    return p


def _make_gif(tmp_path: Path, w: int = 64, h: int = 48) -> Path:
    """Создать минимальный GIF."""
    p = tmp_path / "test.gif"
    header = b"GIF89a"
    dims = struct.pack("<HH", w, h)
    # Packed byte + background + aspect
    p.write_bytes(header + dims + b"\x00\x00\x00")
    return p


def _make_text(tmp_path: Path, content: str = "hello world") -> Path:
    p = tmp_path / "test.txt"
    p.write_text(content)
    return p


def _make_audio(tmp_path: Path) -> Path:
    """Создать фейковый mp3 (заголовок)."""
    p = tmp_path / "test.mp3"
    # ID3 tag header + dummy data
    p.write_bytes(b"ID3" + b"\x00" * 100)
    return p


# ── detect_media_type ─────────────────────────────────────────────────────


class TestDetectMediaType:
    def test_jpeg(self, tmp_path):
        assert detect_media_type(tmp_path / "photo.jpg") == "image"

    def test_png(self, tmp_path):
        assert detect_media_type(tmp_path / "shot.png") == "image"

    def test_webp(self, tmp_path):
        assert detect_media_type(tmp_path / "img.webp") == "image"

    def test_mp3(self, tmp_path):
        assert detect_media_type(tmp_path / "song.mp3") == "audio"

    def test_wav(self, tmp_path):
        assert detect_media_type(tmp_path / "rec.wav") == "audio"

    def test_ogg(self, tmp_path):
        assert detect_media_type(tmp_path / "voice.ogg") == "audio"

    def test_pdf(self, tmp_path):
        assert detect_media_type(tmp_path / "doc.pdf") == "document"

    def test_txt(self, tmp_path):
        assert detect_media_type(tmp_path / "notes.txt") == "document"

    def test_unknown(self, tmp_path):
        assert detect_media_type(tmp_path / "data.xyz") == "other"


class TestDetectMime:
    def test_png(self):
        assert detect_mime("test.png") == "image/png"

    def test_mp3(self):
        assert detect_mime("song.mp3") == "audio/mpeg"

    def test_unknown(self):
        assert detect_mime("data.foobar") == "application/octet-stream"


# ── Image Dimensions ─────────────────────────────────────────────────────


class TestImageDimensions:
    def test_png_dimensions(self, tmp_path):
        p = _make_png(tmp_path, 320, 240)
        data = p.read_bytes()
        w, h = _image_dimensions(data, "image/png")
        assert w == 320
        assert h == 240

    def test_gif_dimensions(self, tmp_path):
        p = _make_gif(tmp_path, 128, 96)
        data = p.read_bytes()
        w, h = _image_dimensions(data, "image/gif")
        assert w == 128
        assert h == 96

    def test_unknown_mime(self):
        w, h = _image_dimensions(b"\x00" * 100, "image/bmp")
        assert w is None
        assert h is None

    def test_short_data(self):
        w, _h = _image_dimensions(b"\x89PNG", "image/png")
        assert w is None  # Too short for IHDR


# ── MediaMeta ─────────────────────────────────────────────────────────────


class TestMediaMeta:
    def test_to_dict(self):
        m = MediaMeta(
            filename="test.png",
            media_type="image",
            mime="image/png",
            size_bytes=1024,
            sha256="abc123",
            width=100,
            height=80,
        )
        d = m.to_dict()
        assert d["filename"] == "test.png"
        assert d["width"] == 100

    def test_from_dict(self):
        d = {"filename": "x.mp3", "media_type": "audio", "mime": "audio/mpeg",
             "size_bytes": 5000, "sha256": "def", "duration_seconds": 3.5}
        m = MediaMeta.from_dict(d)
        assert m.filename == "x.mp3"
        assert m.duration_seconds == 3.5

    def test_roundtrip(self):
        m = MediaMeta(filename="a.pdf", media_type="document", mime="application/pdf",
                      size_bytes=999, sha256="xyz", ocr_text="hello")
        m2 = MediaMeta.from_dict(m.to_dict())
        assert m2.filename == m.filename
        assert m2.ocr_text == "hello"

    def test_defaults(self):
        m = MediaMeta.from_dict({})
        assert m.filename == ""
        assert m.width is None
        assert m.tags == []


# ── compute_file_meta ─────────────────────────────────────────────────────


class TestComputeFileMeta:
    def test_png_meta(self, tmp_path):
        p = _make_png(tmp_path, 200, 150)
        meta = compute_file_meta(p)
        assert meta.filename == "test.png"
        assert meta.media_type == "image"
        assert meta.mime == "image/png"
        assert meta.size_bytes > 0
        assert len(meta.sha256) == 64
        assert meta.width == 200
        assert meta.height == 150

    def test_text_meta(self, tmp_path):
        p = _make_text(tmp_path, "привет мир")
        meta = compute_file_meta(p)
        assert meta.media_type == "document"
        assert meta.size_bytes > 0
        assert meta.width is None

    def test_audio_meta(self, tmp_path):
        p = _make_audio(tmp_path)
        meta = compute_file_meta(p)
        assert meta.media_type == "audio"
        # ffprobe скорее всего не установлен → duration None
        # (не падаем)

    def test_sha256_deterministic(self, tmp_path):
        p = _make_text(tmp_path, "same content")
        m1 = compute_file_meta(p)
        m2 = compute_file_meta(p)
        assert m1.sha256 == m2.sha256


# ── MediaStore ────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.repository import MemoryRepository

    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path / "scratch")})
    repo = MemoryRepository(port)
    return MediaStore(repo)


class TestMediaStore:
    @pytest.mark.asyncio
    async def test_import_png(self, store, tmp_path):
        p = _make_png(tmp_path, 50, 30)
        ref, meta = await store.import_file(p, tags=["test"])
        assert ref.startswith("ref:file:")
        assert meta.media_type == "image"
        assert meta.width == 50
        assert "test" in meta.tags

    @pytest.mark.asyncio
    async def test_import_text(self, store, tmp_path):
        p = _make_text(tmp_path, "документ")
        _ref, meta = await store.import_file(p)
        assert meta.media_type == "document"

    @pytest.mark.asyncio
    async def test_list_media(self, store, tmp_path):
        await store.import_file(_make_png(tmp_path, 10, 10))
        await store.import_file(_make_text(tmp_path, "text"))

        all_media = await store.list_media()
        assert len(all_media) == 2

        images = await store.list_media(media_type="image")
        assert len(images) == 1
        assert images[0].media_type == "image"

    @pytest.mark.asyncio
    async def test_count(self, store, tmp_path):
        await store.import_file(_make_png(tmp_path, 10, 10))
        await store.import_file(_make_text(tmp_path, "x"))

        counts = await store.count()
        assert counts.get("image", 0) == 1
        assert counts.get("document", 0) == 1

    @pytest.mark.asyncio
    async def test_find_by_hash_found(self, store, tmp_path):
        p = _make_png(tmp_path, 20, 20)
        _, meta = await store.import_file(p)

        found = await store.find_by_hash(meta.sha256)
        assert found is not None
        assert found.sha256 == meta.sha256

    @pytest.mark.asyncio
    async def test_find_by_hash_not_found(self, store):
        found = await store.find_by_hash("nonexistent_hash_abc")
        assert found is None

    @pytest.mark.asyncio
    async def test_dedup_by_hash(self, store, tmp_path):
        p = _make_text(tmp_path, "duplicate content")
        _, m1 = await store.import_file(p)

        # Проверяем, что дубликат детектится
        found = await store.find_by_hash(m1.sha256)
        assert found is not None

    @pytest.mark.asyncio
    async def test_content_stored(self, store, tmp_path):
        p = _make_text(tmp_path, "stored content")
        _ref, _ = await store.import_file(p, store_content=True)

        # Проверяем, что content_b64 есть в данных
        rows = await store._repo.query(table="media_documents", limit=1)
        assert len(rows) == 1
        assert "content_b64" in rows[0].data
        decoded = base64.b64decode(rows[0].data["content_b64"])
        assert decoded == b"stored content"

    @pytest.mark.asyncio
    async def test_no_content_when_disabled(self, store, tmp_path):
        p = _make_text(tmp_path, "no store")
        await store.import_file(p, store_content=False)

        rows = await store._repo.query(table="media_documents", limit=1)
        assert len(rows) == 1
        assert "content_b64" not in rows[0].data
