#!/usr/bin/env python3
"""
Octopus VFS OCR worker (host-side).

Сканирует .swarm_scratch на записи таблицы vfs_files (файлообменник вкладки
#files главного дашборда), которые являются изображениями и ещё не прошли OCR.
Запускает tesseract по payload.bin и записывает результат:
  - в meta.json -> attrs.ocr_status / ocr_text / ocr_chars / ocr_at (+ tag ocr)
  - в blob (JSON record) -> content_preview = распознанный текст
    (это делает OCR-текст индексируемым существующим repo.query(text=...) поиском)

tesseract есть на хосте (не в контейнере octopus), поэтому воркер хостовый.
Идемпотентен: повторно не обрабатывает записи с attrs.ocr_status.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRATCH = Path(os.environ.get("OCTOPUS_SCRATCH", "/opt/octopus/.swarm_scratch"))
LANG = os.environ.get("OCTOPUS_OCR_LANG", "eng+rus+ukr")
MAX_FILES = int(os.environ.get("OCTOPUS_VFS_OCR_MAX_FILES", "25"))
TIMEOUT = int(os.environ.get("OCTOPUS_OCR_TIMEOUT", "120"))
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif")


def is_image(mime: str, name: str) -> bool:
    if (mime or "").startswith("image/"):
        return True
    return name.lower().endswith(IMAGE_EXT)


def ocr(path: Path) -> str:
    p = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", LANG],
        text=True, capture_output=True, timeout=TIMEOUT,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-400:])
    return p.stdout.strip()


def main() -> None:
    if not SCRATCH.exists():
        print("scratch absent:", SCRATCH)
        return
    done = err = skipped = 0
    processed = 0
    with os.scandir(SCRATCH) as it:
        entries = list(it)
    for entry in entries:
        if processed >= MAX_FILES:
            break
        try:
            if not entry.is_dir():
                continue
        except OSError:
            continue
        meta_path = Path(entry.path) / "meta.json"
        blob_path = Path(entry.path) / "blob"
        payload_path = Path(entry.path) / "payload.bin"
        if not (meta_path.is_file() and blob_path.is_file() and payload_path.is_file()):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        attrs = meta.get("attrs") or {}
        tags = meta.get("tags") or []
        # only VFS file-manager records
        if attrs.get("_table") != "vfs_files":
            continue
        # idempotent: already OCR'd?
        if "ocr_status" in attrs:
            continue
        # read blob (the JSON file record) for name/mime
        try:
            blob = json.loads(blob_path.read_text(encoding="utf-8"))
        except Exception:
            blob = {}
        name = blob.get("name") or ""
        mime = blob.get("mime") or ""
        if not is_image(mime, name):
            continue

        processed += 1
        try:
            text = ocr(payload_path)
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            attrs["ocr_status"] = "done"
            attrs["ocr_text"] = text[:20000]
            attrs["ocr_chars"] = len(text)
            attrs["ocr_at"] = now
            meta["attrs"] = attrs
            if "ocr" not in tags:
                tags.append("ocr")
            if "rag-ready" not in tags:
                tags.append("rag-ready")
            meta["tags"] = tags
            # make text searchable + previewable via blob.content_preview
            if text:
                blob["content_preview"] = text[:20000]
                blob["ocr_text"] = text[:20000]
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            blob_path.write_text(
                json.dumps(blob, ensure_ascii=False), encoding="utf-8")
            done += 1
            print("VFS OCR OK", entry.name, name, len(text), "chars")
        except Exception as e:  # noqa: BLE001
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            attrs["ocr_status"] = "error"
            attrs["ocr_error"] = str(e)[-400:]
            attrs["ocr_at"] = now
            meta["attrs"] = attrs
            try:
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            err += 1
            print("VFS OCR ERR", entry.name, e, file=sys.stderr)
    # Очистка триггеров мгновенного OCR (re-arm .path-юнита).
    try:
        tdir = Path("/var/lib/octopus/ocr_triggers")
        if tdir.exists():
            for t in tdir.glob("*.trigger"):
                try:
                    t.unlink()
                except Exception:
                    pass
    except Exception:
        pass
    print(f"VFS OCR worker finished: done={done} errors={err} scanned_dirs={len(entries)}")


if __name__ == "__main__":
    main()
