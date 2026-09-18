# Доработки структуры и интерфейса контроля / управления

**Проект:** Бессмертный Рой (Immortal Swarm)  
**Статус:** Фазы 1-3 реализованы ✅

---

## Итоговая сводка

| Метрика | Значение |
|---------|----------|
| Новых файлов | 10 |
| Изменённых файлов | 12 |
| Новых строк кода | ~3 100 |
| Новых тестов | **68** (40 + 28) |
| Тестов всего | **612 passed** |
| Регрессии | 0 |
| Новых зависимостей | 0 |

---

## ✅ Реализовано

### Фаза 1-2: Control Plane SPA + API

**`swarm/api/control_plane.py`** (1 297 строк) — полноценный SPA-сервер:

- **8 страниц UI**: Dashboard, Nodes, Tasks, Memory, Network, LLM, Events, Config
- **11 GET-эндпоинтов**: node/info, peers, gossip, tasks, memory/metrics, llm/usage, config, events/stream, healthz, metrics, manifest.json
- **7 POST-эндпоинтов**: tasks (create), tasks/cancel, memory/insert, network/bootstrap, config/reload, memory/repair/trigger, gossip/inject
- **SSE real-time events** через EventBus
- **Canvas-визуализация** сетевой топологии
- **PWA manifest** (Progressive Web App)
- **Auto-refresh** каждые 10 секунд
- **Responsive** мобильный layout
- **Dark theme** монопространственный

**`swarm/api/auth.py`** — Bearer token + Basic auth + Rate limiting  
**`swarm/api/sse.py`** — EventBus → SSE bridge (21 тип событий)  
**`swarm/observability.py`** — Единый агрегатор метрик через EventBus

### Фаза 3: Инструментирование + Control Actions

**Инструментированные модули:**

| Модуль | Добавлено |
|--------|-----------|
| `swarm/events/events.py` | 7 → **21** тип событий |
| `swarm/llm/router.py` | +`bus=`, +counters, +`usage_snapshot()`, emit LLMCall* events |
| `swarm/memory/composite.py` | +`bus=`, emit Memory* events |
| `swarm/network/gossip.py` | +`bus=`, +counters, +`stats()`, emit Gossip* events |
| `swarm/agent/repair.py` | +`bus=`, +counters, +`stats()`, emit ShardRepair* events |
| `swarm/runtime.py` | Wire bus everywhere, auto-start control plane |
| `swarm/agent/core.py` | Pass bus to RepairLoop |

**POST Control Actions:**

```
POST /api/v1/tasks              → Create task (gossip broadcast)
POST /api/v1/tasks/cancel       → Cancel task in queue
POST /api/v1/memory/insert      → Insert record via repository
POST /api/v1/network/bootstrap  → Bootstrap Kademlia peer
POST /api/v1/config/reload      → Hot-reload gossip/LLM params
POST /api/v1/memory/repair/trigger → Manual shard repair round
POST /api/v1/gossip/inject      → Inject gossip message
```

**Config hot-reload** поддерживает:
- `gossip.interval` / `gossip.fanout`
- `llm.models`
- Emit `ConfigReloaded` event

**Telegram bot** — 5 новых команд:

| Команда | Описание |
|---------|----------|
| `/peers` | Список Kademlia-пиров |
| `/tasks` | Очередь задач |
| `/task DESC` | Создать задачу |
| `/health` | 🟢🟡🔴 статус адаптеров |
| `/alerts` | Последние ошибки |

**Health check plugin** (`swarm/plugins/health_check.py`):
- Периодическая проверка доступности адаптеров
- Emit `AdapterHealthChanged` при смене статуса
- Настройка порогов через `config.yaml`

**CLI dashboard** обновлён — использует `ControlPlaneServer` вместо старого `MemoryDashboard`

---

## 📁 Файлы

### Новые (10)
```
swarm/api/__init__.py              # Пакет
swarm/api/auth.py                  # Auth + rate limiting
swarm/api/control_plane.py         # SPA + JSON API (1297 строк)
swarm/api/sse.py                   # EventBus → SSE bridge
swarm/config/helpers.py            # Shared config parsers
swarm/observability.py             # Runtime aggregator
swarm/plugins/health_check.py      # Periodic health probe
tests/test_control_plane.py        # 40 тестов
tests/test_phase3.py               # 28 тестов
docs/proposals/dashboard-and-control-plane.md
```

### Изменённые (12)
```
config.yaml                        # +dashboard section
node.py                            # Fixed (was corrupted)
swarm/agent/core.py                # Pass bus to RepairLoop
swarm/agent/repair.py              # +bus, +counters, +stats(), +events
swarm/cli.py                       # Dashboard → ControlPlaneServer
swarm/events/__init__.py           # Re-exports 21 types
swarm/events/events.py             # 7 → 21 event types
swarm/llm/router.py                # +bus, +counters, +usage_snapshot, +events
swarm/memory/composite.py          # +bus, +event emission
swarm/memory/telegram.py           # +5 commands, +container
swarm/network/gossip.py            # +bus, +counters, +stats(), +events
swarm/runtime.py                   # Wire bus, start control plane
```

---

## Как использовать

### Встроенный в ноду
```yaml
# config.yaml
dashboard:
  enabled: true
  host: "0.0.0.0"
  port: 9100
  token: "my-secret"  # optional
```
```bash
python node.py start --port 8000
# → Control plane: http://0.0.0.0:9100
```

### Standalone CLI (demo)
```bash
python node.py memory dashboard --demo --port 9100
# Открыть http://127.0.0.1:9100
```

### Telegram
```bash
TELEGRAM_BOT_TOKEN=... python node.py memory tg-bot --allow 1234567
# /health, /peers, /tasks, /task, /alerts + все старые команды
```

### API примеры
```bash
# Создать задачу
curl -X POST http://localhost:9100/api/v1/tasks \
  -H "Authorization: Bearer my-secret" \
  -H "Content-Type: application/json" \
  -d '{"description": "parse prices for BMW X5 windshield"}'

# Вставить запись
curl -X POST http://localhost:9100/api/v1/memory/insert \
  -H "Authorization: Bearer my-secret" \
  -H "Content-Type: application/json" \
  -d '{"table": "parts", "data": {"name": "windshield", "price": 15000}}'

# Hot-reload конфига
curl -X POST http://localhost:9100/api/v1/config/reload \
  -H "Authorization: Bearer my-secret"

# SSE events
curl -N http://localhost:9100/api/v1/events/stream
```
