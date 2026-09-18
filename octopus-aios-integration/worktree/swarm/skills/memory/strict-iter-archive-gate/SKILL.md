---
name: strict-iter-archive-gate
description: Создаёт проверенные tar.gz архивы и `ITER_FILES_ARCHIVED.md` markers для завершённых unmarked `parallel_*` wave-runs. Самостоятельно файлы не удаляет.
---

# SKILL: strict-iter-archive-gate

**Category:** core / storage / durability
**Status:** ACTIVE

## Назначение
Создаёт проверенные tar.gz архивы и `ITER_FILES_ARCHIVED.md` markers для завершённых unmarked `parallel_*` wave-runs. Самостоятельно файлы не удаляет.

## Алгоритм
1. Сканирует `reports/` на каталоги `parallel_*` без marker `ITER_FILES_ARCHIVED.md` и с completion-evidence (`SUMMARY.md`/`SUMMARY_RU.md`/`MANIFEST.json`/`STATUS.md`).
2. Внутри run собирает только `ITER_[0-9]{2,3}.md` (`strict_iter_files`).
3. В режиме `--apply`: создаёт архив во временный `.partial`, добавляя файлы с относительными именами.
4. Верификация архива: count членов, точное membership, restore-smoke (sha256 первого файла из архива == исходный).
5. После всех проверок атомарно `os.replace` переименовывает `.partial` → финальный архив и пишет marker `ITER_FILES_ARCHIVED.md` через временный `.tmp` + `os.replace`.
6. Удаление исходников НЕ выполняется — отдельным skill `archived-report-resurrection-reconciler`.

## Safety gates
1. Каталог должен соответствовать `parallel_*`.
2. Обязателен `SUMMARY.md`, `SUMMARY_RU.md`, `MANIFEST.json` или `STATUS.md`.
3. В архив включаются только `ITER_[0-9]{2,3}.md`.
4. Проверяются count, exact membership, полный SHA256 архива и restore-smoke SHA256.
5. Marker записывается атомарно только после всех проверок.
6. Удаление выполняется отдельным skill `archived-report-resurrection-reconciler`.

## Команды
```bash
python3 code/run.py --json
python3 code/run.py --apply --json --output reports/archive_gate.json
```
