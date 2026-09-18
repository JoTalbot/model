# Сессия: канонический deployment source и аудит drift

---
session_id: "20260814T091000Z-aios-arena-deployment-source"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T09:10:00Z"
updated_utc: "2026-08-14T09:14:00Z"
branch: "agent/20260814-deployment-source"
base_commit: "65c66a8b"
claim: "none (claim closed and removed after implementation)"
---

## Цель

Устранить неоднозначность deployment-источников, не меняя работающий runtime: закрепить канонический production Compose, обезопасить workflows/scripts и добавить воспроизводимый drift-аудит.

## Scope

- Изменено: deploy documentation, manual workflow, helper scripts, read-only audit tool и тесты.
- Не изменено: protected Compose YAML, systemd units, credentials, работающие сервисы/контейнеры.
- Работа выполнена в отдельном worktree.

## Исходное состояние

- Docker labels работающих контейнеров подтверждали `/root/AIOS/docker-compose.prod.yml` как фактически используемый production Compose.
- `.github/workflows/deploy.yml` вызывал `docker compose` без `-f`, поэтому при настроенных secrets мог выбрать локальный `docker-compose.yml`.
- Тот же workflow собирал Docker Hub image, тогда как production Compose использует pinned GHCR digest.
- Workflow отображался как success, хотя deployment job был skipped из-за отсутствующих secrets.
- `deploy/production/docker-compose.prod.yml` — отличающийся legacy v9.1 stack.
- В Git 48 уникальных `aios-*` unit names (50 вместе с Octopus), на хосте установлено 159 AIOS unit files; 116 установленных имён не отслеживались.

## Решения

1. Единственный production Compose — корневой `docker-compose.prod.yml`.
2. Все production-команды обязаны использовать явный `-f docker-compose.prod.yml`.
3. `.github/workflows/deploy.yml` переведён в manual-only и теперь применяет pinned canonical stack после `git merge --ff-only`; несогласованный Docker Hub build удалён.
4. `docker-compose.yml` зафиксирован как local integration, `docker-compose.unified.yml` — experimental, вложенный production Compose — legacy reference.
5. Experimental Swarm требует `AIOS_ALLOW_EXPERIMENTAL_SWARM=1`; all-in-one script явно local/demo.
6. Runtime systemd drift только инвентаризируется. Массовое disable/remove запрещено до поштучного ownership/secret review.

## Изменённые файлы

- `.github/workflows/deploy.yml` — manual canonical deployment без stale Docker Hub build.
- `deploy/DEPLOYMENT_SOURCES.md` — карта источников, entrypoints и reconciliation plan.
- `scripts/audit_deployment_sources.py` — read-only repository/runtime audit.
- `tests/test_deployment_sources.py` — contract tests.
- `deploy-all-in-one.sh` — явный local/demo Compose.
- `scripts/deploy_swarm.sh` — experimental opt-in guard.
- `scripts/start_ui.sh` — пометка simulation/non-production.
- `AGENTS.md` — обязательный production deployment contract.
- `coordination/PROJECT_CONTEXT.md` — актуальный handoff.

## Проверки

- `[PASS]` `python -m py_compile scripts/audit_deployment_sources.py tests/test_deployment_sources.py`.
- `[PASS]` Ruff check/format для audit tool и теста.
- `[PASS]` `pytest tests/test_deployment_sources.py tests/test_release_version.py tests/test_project_health.py -q` — 17 passed.
- `[PASS]` `python scripts/audit_deployment_sources.py --strict` — repository errors 0.
- `[PASS]` `docker compose -f docker-compose.prod.yml config -q` с CI-safe env.
- `[PASS]` deploy workflow YAML parse.
- `[PASS]` `bash -n` для трёх изменённых shell scripts.
- `[NOT RUN]` shellcheck отсутствует на хосте.
- `[EXPECTED NON-ZERO]` runtime strict drift: tracked 48, installed 159, installed-not-tracked 116, tracked-not-installed 5; все AIOS containers используют canonical Compose source.
- `[PASS]` `git diff --check`.

## Git

- Claim commit: `cf23ae22`.
- Implementation commit: `2be18e3a` (`fix(deploy): define canonical production source`).
- Финальный coordination commit находится следующим в истории этого файла.
- Protected Compose и чужие LLM-файлы не менялись.

## Handoff

- Последняя завершённая точка: repository deployment ambiguity устранена; runtime drift измерим и документирован.
- Следующий конкретный шаг: консолидировать dependency declarations либо начать поштучный systemd reconciliation с наиболее критичных активных units.
- Блокеры: 116 unmanaged installed units нельзя безопасно импортировать/удалить массово.
- Риски: full CI/CD остаётся отдельным gated deployment path; его фактический запуск зависит от зелёных integration tests и configured secrets.
- Нельзя делать: считать workflow-level success доказательством rollout без проверки jobs; запускать legacy Compose; массово удалять systemd units.
