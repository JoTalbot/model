# Сессия: единый источник версии

---
session_id: "20260814T090000Z-aios-arena-version-consistency"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T09:00:00Z"
updated_utc: "2026-08-14T09:05:00Z"
branch: "agent/20260814-version-consistency"
base_commit: "96ead91e"
claim: "none (claim closed and removed after implementation)"
---

## Цель

Устранить дрейф package/API/docs version без произвольного изменения канонической версии 19.9.0 и добавить автоматическую проверку согласованности.

## Scope

- Изменено: package/API/docs version policy, `main.py`, docs workflow, исторические документы, целевые тесты.
- Вне scope: LLM proxy, deployment manifests, systemd runtime, dependency consolidation.
- Работа выполнена в отдельном worktree; чужие файлы основного production worktree не затронуты.

## Исходное состояние

- `VERSION`, `pyproject.toml`, `aios_core.__version__`: 19.9.0.
- `main.py` и `ARCHITECTURE.md`: самостоятельный литерал 16.0.0.
- `docs/STATUS.md` и docs workflow: самостоятельный литерал 9.3.0.
- SDK docstring: v4.2.0 при фактической SDK metadata 16.0.0.
- Runtime service labels содержат v20/v21, но относятся к rollout отдельных сервисов и не являются package release.

## Решения

1. Корневой `VERSION` объявлен каноническим источником версии основного продукта.
2. `pyproject.toml` и `aios_core.__version__` остаются обязательными статическими зеркалами, так как packaging/runtime требуют их; drift блокирует тест.
3. Root FastAPI получает версию из `aios_core.__version__`, без литерала.
4. Docs workflow читает и валидирует SemVer из `VERSION`; изменение `VERSION` теперь запускает публикацию документации.
5. Исторические документы сохраняют исходные цифры, но явно помечены snapshot и больше не выглядят текущим статусом.
6. Версия самостоятельного SDK проверяется отдельно и не приравнивается автоматически к package version.

## Изменённые файлы

- `.github/workflows/docs.yml` — динамическая docs version из `VERSION` с SemVer validation.
- `AGENTS.md` — обязательная release/version policy.
- `main.py` — FastAPI metadata использует `AIOS_VERSION`.
- `tests/test_release_version.py` — проверки package, API, docs workflow и SDK.
- `docs/RELEASE_VERSION_POLICY.md` — источник истины и release checklist.
- `mkdocs.yml` — политика добавлена в навигацию.
- `ARCHITECTURE.md`, `EXECUTIVE_SUMMARY.md`, `docs/STATUS.md`, `TELEGRAM_BOT_GUIDE.md` — исторические пометки и ссылки на текущий источник.
- `sdk/__init__.py` — docstring синхронизирован с SDK metadata 16.0.0.
- `coordination/PROJECT_CONTEXT.md` — результат и новый тестовый baseline.

## Проверки

- `[PASS]` `python -m py_compile main.py tests/test_release_version.py sdk/__init__.py`.
- `[PASS]` `pytest tests/test_release_version.py -q` — 4 passed.
- `[PASS]` `pytest tests/test_release_version.py tests/test_project_health.py -q` — 14 passed.
- `[PASS]` `ruff check tests/test_release_version.py sdk/__init__.py`.
- `[PASS]` `ruff format --check tests/test_release_version.py sdk/__init__.py`.
- `[PASS]` YAML structural parse для docs workflow и MkDocs config.
- `[PASS]` MkDocs build в изолированном `/tmp` venv; только существующие информационные предупреждения о страницах вне nav.
- `[PASS]` `git diff --check`.
- `[BASELINE FAIL]` `pytest tests/ -q`: 5 152 collected, 5 139 passed, 7 skipped, 6 failed. Все 6 failures находятся вне изменённого scope: account dialog зависит от live LLM/ignored data, ops usage test пишет в `/root/AIOS`, fintech split assertion. Это выявляет отдельный риск негерметичные тесты.
- `[BASELINE]` полный Ruff для `main.py` всё ещё сообщает существующие mid-file import/E402/I001 нарушения; изменённый верхний import block новых нарушений не добавил.

## Git

- Claim commit: `59b71129`.
- Implementation commit: `c4a788cc` (`fix(release): enforce canonical version metadata`).
- Финальный coordination commit находится следующим в истории этого файла.
- Чужие изменения LLM proxy не индексировались и не менялись.

## Handoff

- Последняя завершённая точка: version drift mitigation реализован и проверен.
- Следующий конкретный шаг: инвентаризировать и унифицировать production deployment sources без изменения runtime до review.
- Блокеры: нет для version fix; полный suite не зелёный из-за 6 существующих негерметичных/функциональных failures.
- Новые риски: тесты используют live LLM, ignored `data/` и абсолютный `/root/AIOS`, поэтому изолированный прогон не полностью воспроизводим.
- Нельзя без отдельного release decision: повышать `VERSION` на основании v20/v21 в названии одного systemd-сервиса.
