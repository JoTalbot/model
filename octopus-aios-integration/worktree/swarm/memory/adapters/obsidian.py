"""Obsidian-flavoured Markdown vault adapter — *karpov / Karpathy* style.

Stores notes as plain ``<vault>/<slug>.md`` files with YAML front-matter and
parses Obsidian-style ``[[wiki-links]]`` so the swarm can build (and walk)
a personal knowledge graph offline and without any external service.

Reference format:  ``ref:obsidian:<slug>``
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swarm.memory.ref_parse import make_ref, parse_ref
from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    RefMeta,
    RefNotFoundError,
)

_WIKI_LINK_RE = re.compile(r"\[\[([^\[\]\|]+?)(?:\|([^\[\]]+?))?\]\]")
_FRONT_MATTER_RE = re.compile(
    r"^---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL
)
_SAFE_SLUG_RE = re.compile(r"[^\w\-\u0080-\uFFFF]+")


def slugify(title: str) -> str:
    """Filesystem-safe slug; preserves Cyrillic and other non-ASCII letters."""
    s = _SAFE_SLUG_RE.sub("-", title.strip()).strip("-").lower()
    return s or "note"


def extract_links(text: str) -> list[str]:
    """Return target note titles referenced as ``[[Target]]`` or ``[[Target|Alias]]``."""
    return [m.group(1).strip() for m in _WIKI_LINK_RE.finditer(text)]


@dataclass
class ObsidianNote:
    slug: str
    title: str
    body: str
    front_matter: dict[str, Any] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)


def _format_front_matter(front: dict[str, Any]) -> str:
    if not front:
        return ""
    parts = ["---"]
    for k, v in front.items():
        if isinstance(v, list):
            parts.append(f"{k}: [{', '.join(json.dumps(x, ensure_ascii=False) for x in v)}]")
        else:
            parts.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    parts.append("---")
    return "\n".join(parts) + "\n\n"


def _parse_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    m = _FRONT_MATTER_RE.match(raw)
    if not m:
        return {}, raw
    body = raw[m.end() :]
    fm: dict[str, Any] = {}
    for line in m.group("body").splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        if v.startswith("[") and v.endswith("]"):
            try:
                fm[k] = json.loads(v)
                continue
            except Exception:
                pass
        try:
            fm[k] = json.loads(v)
        except Exception:
            fm[k] = v
    return fm, body


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ObsidianVaultAdapter:
    """File-system adapter that turns each :class:`Artifact` into a Markdown note.

    ``artifact.attrs["title"]`` controls the visible title (defaults to a
    timestamped slug).  ``artifact.tags`` are written to YAML front-matter so
    Obsidian's own tag explorer picks them up.
    """

    scheme: str = "obsidian"

    def __init__(self, vault_root: Path | str) -> None:
        self._root = Path(vault_root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def vault_root(self) -> Path:
        return self._root

    def _path_for(self, slug: str) -> Path:
        if "/" in slug or "\\" in slug or slug.startswith(".."):
            raise MemoryAdapterError(f"invalid slug: {slug!r}")
        return self._root / f"{slug}.md"

    async def put(self, artifact: Artifact) -> str:
        attrs = artifact.attrs or {}
        title = str(attrs.get("title") or attrs.get("name") or "note")
        slug = slugify(str(attrs.get("slug") or title))
        body = (
            artifact.content
            if isinstance(artifact.content, str)
            else artifact.content.decode("utf-8", errors="replace")
        )

        # Disambiguate so two notes with the same title coexist.
        path = self._path_for(slug)
        counter = 1
        while path.exists():
            cand = f"{slug}-{counter}"
            try:
                path = self._path_for(cand)
            except MemoryAdapterError:
                raise
            counter += 1
        final_slug = path.stem

        front: dict[str, Any] = {
            "title": title,
            "tags": list(artifact.tags or []),
        }
        front.update({k: v for k, v in attrs.items() if k not in {"title", "slug"}})
        text = _format_front_matter(front) + body.rstrip("\n") + "\n"
        path.write_text(text, encoding="utf-8")
        return make_ref("obsidian", final_slug)

    async def get(self, ref: str) -> Artifact:
        scheme, slug = parse_ref(ref)
        if scheme != "obsidian":
            raise MemoryAdapterError(f"unexpected scheme {scheme!r}")
        path = self._path_for(slug)
        if not path.is_file():
            raise RefNotFoundError(ref)
        raw = path.read_text(encoding="utf-8")
        fm, body = _parse_front_matter(raw)
        return Artifact(
            content=body,
            mime="text/markdown",
            tags=list(fm.get("tags") or []),
            provenance={},
            attrs={k: v for k, v in fm.items() if k != "tags"},
        )

    async def exists(self, ref: str) -> bool:
        try:
            scheme, slug = parse_ref(ref)
            if scheme != "obsidian":
                return False
            return self._path_for(slug).is_file()
        except Exception:
            return False

    async def delete(self, ref: str) -> bool:
        scheme, slug = parse_ref(ref)
        if scheme != "obsidian":
            return False
        path = self._path_for(slug)
        if not path.is_file():
            return False
        path.unlink()
        return True

    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]:
        del owner  # not tracked in vault
        wanted = set(tags or [])
        out: list[RefMeta] = []
        for md in sorted(self._root.glob("*.md")):
            raw = md.read_text(encoding="utf-8")
            fm, _ = _parse_front_matter(raw)
            row_tags = list(fm.get("tags") or [])
            if wanted and not wanted.intersection(row_tags):
                continue
            out.append(
                RefMeta(
                    ref=make_ref("obsidian", md.stem),
                    scheme="obsidian",
                    tags=row_tags,
                    block_type="wiki",
                )
            )
        return out

    def capabilities(self) -> Capabilities:
        return Capabilities(
            schemes=frozenset({"obsidian"}),
            supports_search=True,
            supports_delete=True,
            supports_promote=False,
        )

    # ------------------------------------------------------------------
    # Wiki-graph helpers (sync, file-system level — safe to call directly)
    # ------------------------------------------------------------------

    def iter_notes(self) -> Iterable[ObsidianNote]:
        for md in sorted(self._root.glob("*.md")):
            raw = md.read_text(encoding="utf-8")
            fm, body = _parse_front_matter(raw)
            yield ObsidianNote(
                slug=md.stem,
                title=str(fm.get("title") or md.stem),
                body=body,
                front_matter=fm,
                links=extract_links(body),
            )

    def graph(self) -> dict[str, dict[str, list[str]]]:
        """Return ``{slug: {"title": title, "out": [...slug], "in": [...slug]}}``.

        Links are resolved by slugifying each target title.  Dangling links
        (target note not in the vault) are included in ``out`` but never
        appear as keys themselves.
        """
        notes = list(self.iter_notes())
        nodes: dict[str, dict[str, Any]] = {
            n.slug: {"title": n.title, "out": [], "in": []} for n in notes
        }
        for n in notes:
            for target_title in n.links:
                target_slug = slugify(target_title)
                nodes[n.slug]["out"].append(target_slug)
                if target_slug in nodes:
                    nodes[target_slug]["in"].append(n.slug)
        return nodes

    def backlinks(self, slug: str) -> list[str]:
        return self.graph().get(slug, {}).get("in", [])
