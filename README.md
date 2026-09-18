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
| `inventory/repos.md` | Инвентарь репозиториев на хосте: ветка, HEAD, modified/untracked на момент снимка |

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
