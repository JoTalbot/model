# Provenance

Дата снимка: 2026-09-18 (UTC).
Источник: хост arm-server-01 (server id srv-oci-arm-01), Ubuntu 24.04.4, aarch64.

## Соответствие источник → файл

| Файл(-ы) в репо | Источник на хосте | Статус |
|---|---|---|
| `config/hermes/**` | `/opt/hermes/config/` | снято как есть (`*.bak*` удалены) |
| `code/llm/balancer/llm_balancer.py` | `/opt/aios/llm/llm_balancer.py` | untracked на хосте |
| `code/llm/balancer/dynamic_router_autotuner.py` | `/opt/aios/llm/dynamic_router_autotuner.py` | untracked |
| `code/llm/…` (остальные модули) | `/opt/aios/{consensus,evolution,governance,memory_fabric,cognition,tools,automation}` | untracked |
| `code/model-watch/model_watch.py` | `/opt/orchestrator/arena_service/model_watch.py` | tracked, без изменений |
| `code/model-watch/arena-model-watch.{service,timer}` | `/opt/orchestrator/arena_service/` | — |
| `code/orchestrator-scripts/**` | `/opt/orchestrator/` (untracked `*.py`, `tools/`) | untracked |
| `patches/madworld.diff` | `git diff` в `/opt/madworld` (26 KiB) | незапушенные tracked-правки |
| `patches/orchestrator.diff` | `git diff` в `/opt/orchestrator` (0.5 KiB: `arena_agent/arena_auth.py`) | незапушенные tracked-правки |
| `inventory/repos.md` | `git status` всех репозиториев хоста | снимок |

## Редакции

1. Публичный IP хоста → `<PUBLIC_IP_REDACTED>`.
2. Tailnet CGNAT → `<TAILNET_IP_REDACTED>`.
3. `*.bak*`-файлы конфигов и `__pycache__`/`.pyc` исключены.
4. Скрипт `tools/fetch-from-host.sh` (путь в `README.md` → `export.sh`) пересоздаёт
   снимок с хоста при наличии SSH-доступа.

## Второй снимок (2026-09-18, дополнение — полный охват правок)

| Файл(-ы) в репо | Источник на хосте | Статус |
|---|---|---|
| `madworld/modified/**` | `/opt/madworld` — полные копии 6 tracked-изменённых файлов | tracked mod |
| `madworld/untracked/**` | `/opt/madworld` — 107 untracked (без `.dump` бэкапов БД) | untracked |
| `madworld/tracked.diff` | `git diff` в `/opt/madworld` (26 KiB) | — |
| `hermes/modified/**` | `/opt/hermes` — `config/models/hermes-models.yaml`, `deploy/shim/aios_openai_shim.py` | tracked mod |
| `hermes/tracked.diff` | `git diff` в `/opt/hermes` (1.6 KiB, tier `hermes-arena`) | — |
| `hermes/untracked/*.bak-*` | `/opt/hermes` бэкапы shim/models | untracked |
| `octopus/untracked/*.py` | `/opt/octopus` — auth-watchdog, provider-provisioner | untracked |
| `octopus/status.txt`, `diff-stat.txt` | `git status`/`diff --stat` в `/opt/octopus` (ветка `arena/audit-…`) | — |
| `octopus-browser/**` | `/opt/octopus-browser` — 4 untracked (browser-image, cookie-keeper) | untracked |
| `aios` новые файлы | `/opt/aios` — tools (6 новых), evolution_history.json, balancer `.bak` | untracked |
| `inventory/repos-full.md` | Инвентарь всех 19 git-репозиториев хоста | снимок |

Редакции второго снимка: публичный IP в `octopus-provider-provisioner.py` (novnc_url)
→ `<PUBLIC_IP_REDACTED>`; `.pyc`/`__pycache__` и DB-дампы исключены.

## Проверки перед пушем

- Скан секретов (regex): чисто.
- Энтропийный скан длинных токенов: только пути/URL/id — не секреты.
- PII: email'ы — рабочие адреса владельца (в его же функциональном коде и git-diff,
  оставлены как есть); телеграм-token'ы — только из env, без литералов.
