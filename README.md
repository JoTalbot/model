# model

Snapshot-репозиторий: модельные конфиги, LLM-инфраструктурный код и незапушенные
правки автономного окружения **JoTalbot** (хост `arm-server-01`, Ubuntu 24.04 / aarch64).

> Это НЕ пакет и не библиотека — это выгруженная копия конфигураций и кода, который
> управляет выбором моделей и агентной маршрутизацией. Хозяин репозитория — JoTalbot.

## Что лежит

| Путь | Что это |
|---|---|
| `config/hermes/` | Конфиги Hermes-агентов: `models.yaml` (tier → provider), `models/hermes-models.yaml`, профили агентов (`agents/`), политики (`policies/`), сервера (`servers/`), разделяемая память (`MEMORY.global.md`, `SOUL.agent.md`), managed scope |
| `code/llm/balancer/` | LLM-балансировщик: `llm_balancer.py` (11 провайдеров, 5 тиров, health-gated) + `dynamic_router_autotuner.py` |
| `code/llm/` | Смежный модельный код: consensus (`multi_agent_debate.py`), evolution (`auto_evolution_engine.py`), governance (`github_pr_reviewer.py`), memory_fabric (`knowledge_graph.py`), cognition (`vision_pipeline.py`), tools, automation |
| `code/model-watch/` | Монитор флага `agent-model-selector` арены + systemd unit/timer |
| `code/orchestrator-scripts/` | Незакоммиченные скрипты разведки/тестов API (chatgpt-оркестрация), включая `.bak` драйвера Jo |
| `patches/` | Незапушенные git-правки проектов на хосте (tracked diff): `madworld.diff`, `orchestrator.diff` |
| `inventory/repos.md` | Инвентарь репозиториев на хосте на момент первого снимка |
| `inventory/repos-full.md` | **Полный** инвентарь всех 19 git-репозиториев хоста: ветка, HEAD, remote, modified/untracked/unpushed |
| `madworld/` | Полные незакоммиченные правки MadWorld: `modified/` (полные копии 6 tracked-файлов), `untracked/` (107 файлов: remote-operator результаты/состояние, 2 новых CI-workflow, юридические доки, Firebase/FCM-код), `tracked.diff` |
| `hermes/` | Правки Hermes: `modified/` (models.yaml + shim — новый tier `hermes-arena`), `untracked/` (`*.bak`), `tracked.diff` |
| `octopus/` | Правки octopus: 2 новых untracked-скрипта (auth-watchdog, provider-provisioner — IP замаскирован), `status.txt`/`diff-stat.txt` |
| `octopus-browser/` | 4 untracked-файла: browser-image (Dockerfile+start.sh+start-profile9.sh) и cookie-keeper |

> Полный охват незапушенных правок хоста (снимок 2026-09-18): грязными оказались 6 из 19
> репозиториев — aios (181 untracked, из них 158 `.pyc` — байткод исключён), madworld (6 mod
> + 107 untracked), hermes (2 mod + 2 untracked), octopus (1 del + 2 untracked),
> octopus-browser (4 untracked), orchestrator (1 mod + 20 untracked — уже в
> `code/orchestrator-scripts/`). Остальные 13 репозиториев чисты.

## Безопасность (что вырезано перед публикацией)

- **Секреты отсутствуют по построению**: ключи провайдеров живут только в env
  (`/etc/octopus/secrets.env`, `/etc/hermes/shim.env`) и **никогда** не литералами в коде.
  Перед пушем прогнан скан по маскам `ghp_`, `sk-`, `AKIA`, `xox*`, `BEGIN PRIVATE KEY`.
- Публичный IP хоста и tailnet-адрес замаскированы (`<PUBLIC_IP_REDACTED>`,
  `<TAILNET_IP_REDACTED>`) — это инфраструктурный риск, а не данные.
- `.bak`/времянки удалены; `__pycache__`/`.pyc` не включены.

## Восстановление

```sh
# контент — это прямой снимок директорий хоста:
#   config/hermes       <- /opt/hermes/config/
#   code/llm/balancer   <- /opt/aios/llm/       (untracked-файлы)
#   code/model-watch    <- /opt/orchestrator/arena_service/model_watch.py
#   patches/*.diff      <- git diff на хосте
```

`export.sh` в репо пересоздаёт этот снимок (требует SSH-доступ к хосту и путь к нему).
