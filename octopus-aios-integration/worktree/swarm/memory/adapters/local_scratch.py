from __future__ import annotations

import base64
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from swarm.memory.ref_parse import make_ref, parse_ref
from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    RefMeta,
    RefNotFoundError,
    WormConflictError,
)

_BYTES_MARKER = "__gemaxi_bytes_b64__"


def _encode_meta_value(obj: Any) -> Any:
    """Recursively prepare dict/list values for JSON (bytes → marked base64)."""
    if isinstance(obj, bytes):
        return {_BYTES_MARKER: base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, dict):
        return {str(k): _encode_meta_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_encode_meta_value(x) for x in obj]
    if isinstance(obj, tuple):
        return [_encode_meta_value(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    raise MemoryAdapterError(
        f"provenance/attrs must be JSON-serializable (bytes allowed); got {type(obj).__name__}"
    )


def _decode_meta_value(obj: Any) -> Any:
    if isinstance(obj, dict):
        if len(obj) == 1 and _BYTES_MARKER in obj:
            return base64.b64decode(obj[_BYTES_MARKER])
        return {k: _decode_meta_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode_meta_value(x) for x in obj]
    return obj


class LocalScratchAdapter:
    """Stores artifacts as `root/<opaque>/blob` + `meta.json` on local disk.

    WORM: with tag ``dur:worm`` and ``attrs["worm_base_ref"]`` set to an existing
    ``ref:file:...`` under this root, a second ``put`` with different body raises
    ``WormConflictError``; identical body returns the same ref (idempotent).
    """

    scheme: str = "file"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _dir_for(self, opaque: str) -> Path:
        return self._root / opaque

    async def put(self, artifact: Artifact) -> str:
        if isinstance(artifact.content, str):
            blob = artifact.content.encode("utf-8")
        else:
            blob = artifact.content

        if "dur:worm" in artifact.tags and artifact.attrs:
            base_ref = artifact.attrs.get("worm_base_ref")
            if base_ref:
                scheme, opaque = parse_ref(base_ref)
                if scheme != "file":
                    raise MemoryAdapterError("worm_base_ref must use scheme file")
                d = self._dir_for(opaque)
                try:
                    d.resolve().relative_to(self._root.resolve())
                except ValueError as exc:
                    raise MemoryAdapterError(
                        "worm_base_ref directory escapes scratch root"
                    ) from exc
                blob_path = d / "blob"
                meta_path = d / "meta.json"
                if blob_path.is_file() and meta_path.is_file():
                    existing = blob_path.read_bytes()
                    if existing != blob:
                        raise WormConflictError(
                            f"WORM: content at {base_ref} may not be overwritten"
                        )
                    return base_ref

        opaque = str(uuid.uuid4())
        d = self._dir_for(opaque)
        d.mkdir(parents=True, exist_ok=True)

        meta = {
            "mime": artifact.mime,
            "tags": artifact.tags,
            "provenance": _encode_meta_value(artifact.provenance),
            "attrs": _encode_meta_value(artifact.attrs),
        }
        (d / "blob").write_bytes(blob)
        (d / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return make_ref("file", opaque)

    async def get(self, ref: str) -> Artifact:
        scheme, opaque = parse_ref(ref)
        assert scheme == "file"
        d = self._dir_for(opaque)
        blob_path = d / "blob"
        meta_path = d / "meta.json"
        if not blob_path.is_file() or not meta_path.is_file():
            raise RefNotFoundError(ref)
        blob = blob_path.read_bytes()
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        return Artifact(
            content=blob,
            mime=raw["mime"],
            tags=list(raw["tags"]),
            provenance=_decode_meta_value(raw["provenance"]),
            attrs=_decode_meta_value(raw["attrs"]),
        )

    async def exists(self, ref: str) -> bool:
        scheme, opaque = parse_ref(ref)
        if scheme != "file":
            return False
        d = self._dir_for(opaque)
        return (d / "blob").is_file() and (d / "meta.json").is_file()

    async def delete(self, ref: str) -> bool:
        scheme, opaque = parse_ref(ref)
        if scheme != "file":
            return False
        d = self._dir_for(opaque)
        if not d.is_dir():
            return False
        shutil.rmtree(d)
        return True

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        del owner  # local scratch does not track owner in v1.
        wanted = set(tags)
        out: list[RefMeta] = []
        if not self._root.exists():
            return out

        for entry in self._root.iterdir():
            if not entry.is_dir():
                continue
            meta_path = entry / "meta.json"
            if not meta_path.is_file():
                continue
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            row_tags = list(raw.get("tags") or [])
            if wanted and not wanted.intersection(row_tags):
                continue
            attrs = _decode_meta_value(raw.get("attrs"))
            out.append(
                RefMeta(
                    ref=make_ref("file", entry.name),
                    scheme="file",
                    tags=row_tags,
                    block_type=(attrs or {}).get("block_type"),
                )
            )
        return out

    def capabilities(self) -> Capabilities:
        return Capabilities(
            schemes=frozenset({"file"}),
            supports_search=True,
            supports_delete=True,
            supports_promote=False,
        )
