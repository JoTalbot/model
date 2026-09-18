"""
swarm/api/files_endpoints.py
─────────────────────────────
Файлообменник для веб-админки (Google-Drive-style).

Использует VirtualFileSystem из container.vfs для МЕТАДАННЫХ и
параллельно сохраняет байтовый payload файла в
.swarm_scratch/<ref-uuid>/payload.bin (для бинарных файлов любого размера).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

_LOG = logging.getLogger("swarm.api.files_endpoints")

SCRATCH_DIR = Path("/app/.swarm_scratch")
POOL_DIR = Path("/app/memory_pool")
PAYLOAD_NAME = "payload.bin"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_repo(container):
    from swarm.memory.repository import MemoryRepository
    mp = container.agent.memory_port if container.agent else None
    if mp is None:
        return None
    return MemoryRepository(mp)


def _ref_uuid(ref: str) -> str:
    """ref выглядит как 'ref:file:<uuid>'. Достаём uuid."""
    if not ref:
        return ""
    parts = ref.split(":")
    return parts[-1] if parts else ref


def _payload_path(ref: str) -> Path:
    uid = _ref_uuid(ref)
    if not uid:
        return Path("/dev/null")
    if ref.startswith("sha256:"):
        return POOL_DIR / uid
    p_blob = SCRATCH_DIR / uid / "blob"
    if p_blob.exists(): return p_blob
    return SCRATCH_DIR / uid / PAYLOAD_NAME



def _row_to_file_dict(row) -> dict:
    data = getattr(row, "data", {}) or {}
    attrs = getattr(row, "attrs", {}) or {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(attrs, dict):
        attrs = {}
    ref = getattr(row, "ref", "")
    has_payload = _payload_path(ref).exists() if ref else False
    ocr_status = attrs.get("ocr_status")
    ocr_text = attrs.get("ocr_text") or data.get("ocr_text") or ""
    return {
        "ref":     ref,
        "name":    data.get("name") or data.get("filename") or "unnamed",
        "path":    attrs.get("path") or data.get("path") or "/",
        "size":    int(data.get("size") or 0),
        "mime":    data.get("mime") or "application/octet-stream",
        "preview": (data.get("content_preview") or data.get("content") or "")[:300],
        "tags":    list(getattr(row, "tags", []) or []),
        "ts":      attrs.get("_ts") or 0,
        "vfs_id":  attrs.get("vfs_id", ""),
        "has_payload": has_payload,
        "ocr_status": ocr_status,
        "ocr_text": ocr_text[:20000] if isinstance(ocr_text, str) else "",
        "ocr_chars": attrs.get("ocr_chars"),
    }


# ───────────────────────────── list ─────────────────────────────────────────

def handle_files_list(container, path: str = "/", search: str = "", tag: str = "") -> dict:
    try:
        repo = _get_repo(container)
        if repo is None:
            return {"ok": False, "files": [], "error": "memory_port not available"}

        async def _q():
            tags_filter = ["vfs"]
            if tag and tag != "vfs":
                tags_filter.append(tag)
            if search:
                rows = await repo.query(table="vfs_files", text=search, tags=tags_filter, limit=500)
            else:
                rows = await repo.query(table="vfs_files", tags=tags_filter, limit=500)
            return rows

        rows = _run(_q())
        files = [_row_to_file_dict(r) for r in rows]

        if path and path != "*":
            norm = path.rstrip("/") or "/"
            files = [
                f for f in files
                if (f["path"].rstrip("/") or "/") == norm
                or (norm == "/" and f["path"] in ("", "/"))
            ]

        files.sort(key=lambda f: (-(f["ts"] or 0), f["name"]))
        return {"ok": True, "files": files, "count": len(files), "path": path}
    except Exception as exc:
        _LOG.exception("files_list error")
        return {"ok": False, "files": [], "error": str(exc)}


def handle_files_tree(container) -> dict:
    try:
        repo = _get_repo(container)
        if repo is None:
            return {"ok": False, "tree": {}, "error": "memory_port not available"}

        async def _q():
            return await repo.query(table="vfs_files", tags=["vfs"], limit=5000)

        rows = _run(_q())
        paths = set(["/"])
        sizes_by_path = {}
        counts_by_path = {}
        for r in rows:
            data = getattr(r, "data", {}) or {}
            attrs = getattr(r, "attrs", {}) or {}
            p = (attrs.get("path") or data.get("path") or "/").rstrip("/") or "/"
            parts = [x for x in p.split("/") if x]
            cur = ""
            paths.add("/")
            for x in parts:
                cur = cur + "/" + x
                paths.add(cur)
            sizes_by_path[p] = sizes_by_path.get(p, 0) + int(data.get("size") or 0)
            counts_by_path[p] = counts_by_path.get(p, 0) + 1

        tree = []
        for p in sorted(paths):
            tree.append({
                "path": p,
                "name": p.split("/")[-1] or "root",
                "depth": (p.count("/") if p != "/" else 0),
                "files_count": counts_by_path.get(p, 0),
                "total_size": sizes_by_path.get(p, 0),
            })
        return {"ok": True, "tree": tree, "paths_count": len(tree)}
    except Exception as exc:
        _LOG.exception("files_tree error")
        return {"ok": False, "tree": [], "error": str(exc)}


# ───────────────────────────── upload ────────────────────────────────────────

def handle_files_upload(container, body_bytes: bytes, headers: dict) -> dict:
    try:
        name = unquote(headers.get("X-File-Name", "").strip() or "unnamed.bin")
        path = unquote(headers.get("X-File-Path", "").strip() or "/")
        mime = headers.get("X-File-Mime", "").strip()
        tags_csv = unquote(headers.get("X-File-Tags", "").strip())
        encoding = headers.get("X-Encoding", "").strip().lower()

        if encoding == "base64":
            try:
                body_bytes = base64.b64decode(body_bytes)
            except Exception as e:
                return {"ok": False, "error": f"base64 decode failed: {e}"}

        if not mime:
            mime, _ = mimetypes.guess_type(name)
            mime = mime or "application/octet-stream"

        tags = [t.strip() for t in tags_csv.split(",") if t.strip()]

        if not path.startswith("/"):
            path = "/" + path
        path = path.rstrip("/") or "/"

        vfs = getattr(container, "vfs", None)
        if vfs is None:
            return {"ok": False, "error": "VFS not available"}

        async def _store():
            return await vfs.store_file(
                name=name,
                content=body_bytes,
                path=path,
                tags=tags,
                mime=mime,
            )

        vfile = _run(_store())

        # Сохраняем сырой payload рядом с meta-записью
        try:
            pp = _payload_path(vfile.ref)
            pp.parent.mkdir(parents=True, exist_ok=True)
            pp.write_bytes(body_bytes)
            _LOG.info("payload written: %s (%d bytes)", pp, len(body_bytes))
        except Exception as e:
            _LOG.warning("payload write failed: %s", e)

        # Мгновенный OCR: для изображений роняем триггер-файл, который host-side
        # .path-юнит ловит и сразу запускает octopus-vfs-ocr-worker (tesseract
        # доступен только на хосте). Без триггера OCR подхватит таймер (до 5 мин).
        try:
            _is_image = (mime or "").startswith("image/") or name.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif")
            )
            if _is_image:
                _td = Path("/var/lib/octopus/ocr_triggers")
                _td.mkdir(parents=True, exist_ok=True)
                (_td / (_ref_uuid(vfile.ref) + ".trigger")).write_text(
                    vfile.ref, encoding="utf-8"
                )
        except Exception as e:
            _LOG.warning("ocr trigger write failed: %s", e)

        return {
            "ok":   True,
            "ref":  vfile.ref,
            "name": vfile.name,
            "path": vfile.path,
            "size": vfile.size,
            "mime": vfile.mime,
        }
    except Exception as exc:
        _LOG.exception("upload error")
        return {"ok": False, "error": str(exc)}


# ───────────────────────────── download ─────────────────────────────────────

def handle_files_download(container, ref: str):
    """(mime, filename, bytes) или None."""
    try:
        mp = container.agent.memory_port if container.agent else None
        if not mp:
            return None
        async def _get():
            return await mp.get(ref)
        art = _run(_get())
        if art is None:
            return None
        # Метаданные
        meta = {}
        if isinstance(art.content, str):
            try:
                meta = json.loads(art.content)
            except Exception:
                meta = {}
        name = meta.get("name", ref.split(":")[-1] or "file.bin")
        mime = meta.get("mime", "application/octet-stream")

        # Сначала пытаемся прочитать полный payload
        pp = _payload_path(ref)
        if pp.exists():
            try:
                return (mime, name, pp.read_bytes())
            except Exception as e:
                _LOG.warning("payload read failed for %s: %s", ref, e)

        # Fallback: preview из meta
        preview = meta.get("content_preview", "")
        if isinstance(preview, str):
            return (mime if mime.startswith("text/") else "text/plain",
                    name, preview.encode("utf-8"))
        if isinstance(preview, (bytes, bytearray)):
            return (mime, name, bytes(preview))
        # Последний шанс — отдать сам JSON-meta как текст
        return ("text/plain", name, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    except Exception:
        _LOG.exception("download error")
        return None


# ───────────────────────────── delete / move / tag ──────────────────────────

def handle_files_delete(container, body: dict) -> dict:
    ref = body.get("ref", "").strip()
    if not ref:
        return {"ok": False, "error": "ref required"}
    try:
        repo = _get_repo(container)
        if repo is None:
            return {"ok": False, "error": "no repo"}
        async def _del():
            return await repo.delete(ref)
        ok = _run(_del())
        # удаляем payload
        try:
            pp = _payload_path(ref)
            if pp.exists():
                pp.unlink()
        except Exception:
            pass
        return {"ok": bool(ok), "ref": ref}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_files_move(container, body: dict) -> dict:
    ref = body.get("ref", "").strip()
    new_path = body.get("new_path", "").strip() or "/"
    if not ref:
        return {"ok": False, "error": "ref required"}
    if not new_path.startswith("/"):
        new_path = "/" + new_path
    try:
        repo = _get_repo(container)
        vfs = getattr(container, "vfs", None)
        mp = container.agent.memory_port if container.agent else None
        if not repo or not vfs or not mp:
            return {"ok": False, "error": "components missing"}

        # Читаем payload (если есть) и meta, создаём новую запись, удаляем старую
        pp_old = _payload_path(ref)
        payload = pp_old.read_bytes() if pp_old.exists() else b""

        async def _move():
            art = await mp.get(ref)
            if art is None:
                return None
            try:
                meta = json.loads(art.content) if isinstance(art.content, str) else {}
            except Exception:
                meta = {}
            name = meta.get("name", "moved.bin")
            mime = meta.get("mime", "application/octet-stream")
            new_vf = await vfs.store_file(
                name=name,
                content=payload if payload else (meta.get("content_preview", "") or "").encode("utf-8"),
                path=new_path,
                tags=list(art.tags or []),
                mime=mime,
            )
            return new_vf

        vf = _run(_move())
        if vf is None:
            return {"ok": False, "error": "source not found"}
        # пересохраняем payload под новым ref
        if payload:
            try:
                pp_new = _payload_path(vf.ref)
                pp_new.parent.mkdir(parents=True, exist_ok=True)
                pp_new.write_bytes(payload)
            except Exception:
                pass
        # удаляем старое
        try:
            _run(repo.delete(ref))
            if pp_old.exists():
                pp_old.unlink()
        except Exception:
            pass
        return {"ok": True, "ref": vf.ref, "path": vf.path}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_files_mkdir(container, body: dict) -> dict:
    path = body.get("path", "").strip() or "/"
    if not path.startswith("/"):
        path = "/" + path
    try:
        vfs = getattr(container, "vfs", None)
        if vfs is None:
            return {"ok": False, "error": "VFS not available"}
        async def _mk():
            return await vfs.store_file(
                name=".keep",
                content=b"",
                path=path,
                tags=["folder", "keep"],
                mime="application/x-directory",
            )
        vf = _run(_mk())
        return {"ok": True, "path": vf.path, "ref": vf.ref}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_files_tag(container, body: dict) -> dict:
    ref = body.get("ref", "").strip()
    tags = body.get("tags", [])
    if not ref or not isinstance(tags, list):
        return {"ok": False, "error": "ref and tags[] required"}
    try:
        repo = _get_repo(container)
        mp = container.agent.memory_port if container.agent else None
        if not repo or not mp:
            return {"ok": False, "error": "no repo"}

        async def _tag():
            art = await mp.get(ref)
            if art is None:
                return False
            new_tags = list(tags)
            if "vfs" not in new_tags:
                new_tags.append("vfs")
            from swarm.memory.port import Artifact
            new_art = Artifact(
                content=art.content,
                mime=art.mime,
                tags=new_tags,
                provenance=getattr(art, "provenance", {}) or {},
                attrs=getattr(art, "attrs", {}) or {},
            )
            new_ref = await mp.put(new_art)
            await repo.delete(ref)
            return new_ref

        new_ref = _run(_tag())
        if not new_ref:
            return {"ok": False, "error": "file not found"}
        # переносим payload
        try:
            pp_old = _payload_path(ref)
            if pp_old.exists():
                pp_new = _payload_path(new_ref)
                pp_new.parent.mkdir(parents=True, exist_ok=True)
                pp_new.write_bytes(pp_old.read_bytes())
                pp_old.unlink()
        except Exception:
            pass
        return {"ok": True, "new_ref": new_ref, "tags": tags}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ───────────────────────────── stats ────────────────────────────────────────

def handle_files_stats(container) -> dict:
    try:
        repo = _get_repo(container)
        if repo is None:
            return {"ok": False, "error": "no repo"}

        async def _q():
            return await repo.query(table="vfs_files", tags=["vfs"], limit=10000)
        rows = _run(_q())

        total_bytes = 0
        by_mime: dict[str, dict] = {}
        by_path: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        recent = []
        for r in rows:
            d = _row_to_file_dict(r)
            total_bytes += d["size"]
            mime_key = d["mime"].split("/")[0] if "/" in d["mime"] else d["mime"]
            entry = by_mime.setdefault(mime_key, {"count": 0, "size": 0})
            entry["count"] += 1
            entry["size"] += d["size"]
            by_path[d["path"]] = by_path.get(d["path"], 0) + 1
            for t in d["tags"]:
                if t in ("vfs", "folder", "keep") or t.startswith("table:"):
                    continue
                by_tag[t] = by_tag.get(t, 0) + 1
            recent.append({"name": d["name"], "path": d["path"], "ts": d["ts"], "ref": d["ref"]})

        recent.sort(key=lambda x: -(x["ts"] or 0))
        return {
            "ok": True,
            "files_total":   len(rows),
            "bytes_total":   total_bytes,
            "by_mime":       by_mime,
            "by_path":       by_path,
            "by_tag":        by_tag,
            "recent":        recent[:10],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
