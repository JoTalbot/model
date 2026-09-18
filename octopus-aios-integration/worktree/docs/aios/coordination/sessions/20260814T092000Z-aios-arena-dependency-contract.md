# Сессия: dependency contract и воспроизводимый lock

---
session_id: "20260814T092000Z-aios-arena-dependency-contract"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T09:20:00Z"
updated_utc: "2026-08-14T09:24:00Z"
branch: "agent/20260814-dependency-contract"
base_commit: "3c53eb12"
claim: "none (claim closed and removed after implementation)"
---

## Цель

Определить роли dependency-файлов, устранить конфликт metadata/production lock и добавить автоматический воспроизводимый контракт без массового обновления пакетов.

## Исходное состояние

- `pyproject.toml`: 12 minimal package dependencies.
- `requirements.txt`: 45 full production direct dependencies.
- `requirements.lock`: 198 exact resolved packages; Dockerfile устанавливает lock.
- `requests` и `python-dotenv` были core metadata, но не direct production input.
- `websockets>=16.1.1` в metadata конфликтовал с `web3==7.16.0`, который требует `websockets<16`; production lock содержит 15.0.1.
- Хостовый venv `pip check` имел посторонний gTTS/click конфликт и не являлся чистой production-проверкой.

## Решения

1. Роли формализованы: `pyproject` = minimal, `requirements.txt` = full direct production, lock = exact production resolution, dev extra = tooling.
2. Инвариант: minimal ⊆ direct ⊆ lock; все constraints удовлетворяются locked versions.
3. WebSockets согласован как `>=15.0,<16.0`, совместимый с Web3 и lock 15.0.1.
4. `requests` и `python-dotenv` добавлены как явные direct requirements; остальные minimal constraints синхронизированы.
5. Lock не изменён: Python 3.11 pip-compile воспроизвёл все 198 exact pins без различий.
6. `pip freeze` запрещён для production lock; массовые upgrades выделяются в отдельную supply-chain задачу.

## Изменённые файлы

- `pyproject.toml` — исправлен конфликт WebSockets и описана minimal role.
- `requirements.txt` — 47 direct requirements с синхронизированными core constraints.
- `docs/DEPENDENCY_POLICY.md` — роли, generation command и review policy.
- `scripts/check_dependency_contract.py` — автоматическая проверка subset/specifier/Docker invariants.
- `tests/test_dependency_contract.py` — contract tests и regression WebSockets/Web3.
- `AGENTS.md` — обязательные dependency rules.
- `mkdocs.yml` — политика добавлена в документацию.
- `coordination/PROJECT_CONTEXT.md` — обновлён handoff.

## Проверки

- `[PASS]` Ruff check/format и `py_compile` для checker/tests.
- `[PASS]` `python scripts/check_dependency_contract.py --strict` — minimal 12, direct 47, lock 198, errors 0.
- `[PASS]` `pytest tests/test_dependency_contract.py tests/test_release_version.py tests/test_deployment_sources.py tests/test_project_health.py -q` — 20 passed.
- `[PASS]` pip-compile в контейнере production image с Python 3.11.15 воспроизвёл все 198 package/version pins без изменений.
- `[PASS]` `python -m pip check` в чистом production image — `No broken requirements found`.
- `[PASS]` MkDocs config parse и `git diff --check`.
- `[UNCHANGED]` `requirements.lock` не имеет diff; массовый upgrade не выполнялся.

## Git

- Claim commit: `a34edfc5`.
- Implementation commit: `7bd3e1e7` (`fix(deps): align production dependency contract`).
- Финальный coordination commit находится следующим в истории.
- Чужие LLM-файлы не затронуты.

## Handoff

- Последняя точка: dependency metadata/direct/lock contract согласован и автоматически проверяется.
- Следующий конкретный шаг: исправить глобальный `.gitignore` для `*.json` через сначала read-only inventory и allow/deny policy либо заняться герметичностью 6 failing tests.
- Блокеры: нет.
- Риски: плановый upgrade lock остаётся отдельной задачей; нельзя смешивать его с функциональными изменениями.
