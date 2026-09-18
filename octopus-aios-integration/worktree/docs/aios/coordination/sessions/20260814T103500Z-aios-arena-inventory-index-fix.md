# Сессия: inventory из Git index, не worktree

---
session_id: "20260814T103500Z-aios-arena-inventory-index-fix"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T10:35:00Z"
updated_utc: "2026-08-14T10:45:00Z"
branch: "agent/20260814-project-inventory"
base_commit: "2af3651a"
claim: "none (claim closed and removed after correction)"
---

## Причина и исправление

Первый generator читал mutable worktree, поэтому чужой unstaged LLM diff делал snapshot stale. Чтение переведено на stage-0 Git index: `git ls-files -s` + один `git cat-file --batch` через `communicate()`.

## Проверки

- `[PASS]` 3 inventory regression tests.
- `[PASS]` временное unstaged изменение `README.md` не меняет lines/bytes.
- `[PASS]` generator `--check` current.
- `[PASS]` Git-index mode учитывает 3 symlink blobs, ранее пропущенные worktree `is_file()`.
- `[PASS]` diff hygiene.

## Git

- Claim commit: `a7119005`.
- Implementation commits: `42ba5e15` (Git index blobs), `f6ada673` (exclude all coordination metrics).

## Handoff

Inventory теперь безопасен для грязного общего worktree и параллельных агентов.
