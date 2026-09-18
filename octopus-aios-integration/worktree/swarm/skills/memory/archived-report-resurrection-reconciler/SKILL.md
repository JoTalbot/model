---
name: archived-report-resurrection-reconciler
description: После verified compaction удалённые ITER-файлы могут повторно появиться из-за legacy multisync, который не распространяет удаления. Это увеличивает диск и inode count, хотя проверенный архив уже существует.
---

# SKILL: archived-report-resurrection-reconciler

**Category:** core / storage / durability
**Status:** ACTIVE
**Purpose:** безопасно удаляет только воскресшие `ITER_[0-9]{2,3}.md` из уже archive-verified wave-run каталогов.

## Контекст
После verified compaction удалённые ITER-файлы могут повторно появиться из-за legacy multisync, который не распространяет удаления. Это увеличивает диск и inode count, хотя проверенный архив уже существует.

## Алгоритм
1. Найти только top-level marker `reports/*/ITER_FILES_ARCHIVED.md`.
2. Преобразовать legacy `/root/agents/` в канонический `/mnt/agents/`.
3. Проверить наличие архива и совпадение полного SHA256 с marker.
4. Проверить количество strict ITER members внутри tar.gz.
5. Проверить, что каждый воскресший strict ITER представлен в архиве.
6. Выполнить restore-smoke: сравнить SHA256 одного живого файла с его содержимым из архива.
7. В dry-run только сформировать отчёт.
8. В `--apply` удалить исключительно strict ITER-файлы из exact run directory; не трогать `SUMMARY`, `SMOKE`, `STATUS`, `MANIFEST`, board и marker.
9. После применения проверить remaining=0, health и disk.

## Команды
```bash
python3 code/run.py --json
python3 code/run.py --apply --json --output reports/reconcile.json
pytest -q tests/test_reconciler.py
```

## Safety
- При missing archive, SHA mismatch, member-count mismatch или restore-smoke mismatch удаление блокируется.
- Не выполняет IPFS/CAS/Docker GC.
- Не изменяет внешние ресурсы, сервисы и другие проекты.
