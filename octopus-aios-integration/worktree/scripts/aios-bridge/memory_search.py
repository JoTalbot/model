"""Memory-search bridge (Wave 3, items 7+9) — PREPARED, NOT WIRED.

AIOS served memory search via ``memory_search_router`` (FastAPI router with
``/mnt/agents`` on sys.path). Octopus keeps the skill's own engine
(``swarm/skills/memory/pwa-file-exchange/code/memory_api.py::search_memory``,
plain LIKE search over SQLite) and this module adapts it:

- :func:`search` — stdlib-only query helper (CLI + library use)
- :func:`create_router` — FastAPI router factory (lazy ``fastapi`` import)

Opt-in only: nothing imports this module yet. See
``docs/aios/MEMORY_SEARCH_REPLACEMENT.md`` for the swap procedure.

Env:
    OCTOPUS_ROOT — repo root (default ``/opt/octopus``)
    OCTOPUS_MEMORY_DB — SQLite path (default ``/var/lib/octopus/memory_skill.db``)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

DEFAULT_DB = "/var/lib/octopus/memory_skill.db"


def _skill_path() -> Path:
    root = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
    return (
        root
        / "swarm"
        / "skills"
        / "memory"
        / "pwa-file-exchange"
        / "code"
        / "memory_api.py"
    )


def _load_skill():
    """Load the skill module by path (skills are docs+code, not a package)."""
    path = _skill_path()
    if not path.exists():
        raise FileNotFoundError(f"memory skill not found: {path}")
    spec = importlib.util.spec_from_file_location("octopus_memory_api", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["octopus_memory_api"] = mod
    spec.loader.exec_module(mod)
    return mod


def search(query: str, limit: int = 20) -> list[dict]:
    """Search stored memories (LIKE over title/content/tags, newest first)."""
    if not query or not query.strip():
        return []
    mod = _load_skill()
    db_path = os.environ.get("OCTOPUS_MEMORY_DB", DEFAULT_DB)
    rows = mod.search_memory(query.strip(), db_path=db_path)
    return rows[: max(limit, 0)]


def create_router():
    """Build a FastAPI router exposing POST /memory/search (lazy import)."""
    from fastapi import APIRouter  # lazy: optional dependency
    from pydantic import BaseModel

    class _Query(BaseModel):
        query: str
        limit: int = 20

    router = APIRouter(prefix="/memory", tags=["memory"])

    @router.post("/search")
    def _search(body: _Query):
        return {"results": search(body.query, body.limit)}

    return router


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].strip():
        print(f"Usage: {Path(argv[0]).name} <query>", file=sys.stderr)
        return 2
    print(json.dumps(search(argv[1]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
