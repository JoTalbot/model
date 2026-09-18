# Бессмертный Рой — Design Specification

## Обзор

Распределённая P2P-сеть автономных ИИ-агентов:
- Принимают высокоуровневые цели от человека, самостоятельно декомпозируют на подзадачи
- Общаются через Gossip-броадкасты + DHT + прямой RPC
- Хранят всю память (диалоги, результаты задач, базу знаний) в Reed-Solomon-шардированном распределённом хранилище
- Используют OpenRouter LLM (Claude, Grok, Llama) с пулом ключей и автоматическим failover

## Архитектурный подход: Модульный монолит

Один процесс на ноду, внутри — чётко разделённые модули с определёнными интерфейсами.

```
┌─────────────────────────────────────────┐
│              Node Process               │
├─────────────────────────────────────────┤
│  CLI / API Entry                        │
├─────────────────────────────────────────┤
│  SwarmAgent Core                        │
│  ├── Task Manager (decompose/dispatch)  │
│  └── Skills (Parser, Chat)              │
├─────────────────────────────────────────┤
│  LLM Router + Key Pool                  │
├─────────────────────────────────────────┤
│  Distributed Memory                     │
│  └── Reed-Solomon Encoder               │
├─────────────────────────────────────────┤
│  Network Layer                          │
│  ├── Kademlia DHT                       │
│  ├── Gossip Protocol                    │
│  └── Direct RPC                         │
└─────────────────────────────────────────┘
```

## Файловая структура

```
gemaxi/
├── node.py                  # Точка входа — запускает ноду
├── config.yaml              # Конфиг (порт, bootstrap-ноды, API-ключи)
├── requirements.txt         # Зависимости
├── swarm/
│   ├── __init__.py
│   ├── network/
│   │   ├── __init__.py
│   │   ├── kademlia.py      # DHT: peer discovery + key-value storage
│   │   ├── gossip.py        # Push-based gossip broadcasts
│   │   └── rpc.py           # Direct node-to-node TCP (msgpack)
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── store.py         # High-level API: put/get/delete/search
│   │   └── erasure.py       # Reed-Solomon shard/reconstruct
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── core.py          # Base SwarmAgent class + main loop
│   │   ├── task_manager.py  # Task decomposition and distribution
│   │   └── skills.py        # WebParserSkill, ChatSkill
│   └── llm/
│       ├── __init__.py
│       ├── router.py        # OpenRouter client + model failover
│       └── key_pool.py      # API key rotation + rate limit tracking
└── tests/
```

## Слой 1: Сеть (P2P)

### Kademlia DHT

- 160-bit Node ID (SHA-1 от случайного seed)
- K-buckets для routing table (k=20)
- Операции: `PING`, `STORE`, `FIND_NODE`, `FIND_VALUE`
- Библиотека: `kademlia` (asyncio-нативный Python-пакет)
- Bootstrap: при старте нода подключается к известному адресу и через FIND_NODE заполняет свою routing table

### Gossip-протокол

- Push-based: каждые 5 секунд нода отправляет свежие апдейты 3 случайным соседям
- Типы сообщений:
  - `NODE_JOIN` — новая нода в сети
  - `NODE_LEAVE` — нода ушла/упала
  - `TASK_BROADCAST` — новая задача ищет исполнителя
  - `STATE_UPDATE` — изменение состояния агента
- Дедупликация: каждое сообщение имеет UUID, нода хранит seen-set последних 1000 ID
- Реализация: кастомная, поверх asyncio UDP

### RPC (прямая связь)

- asyncio TCP streams между конкретными нодами
- Сериализация: MessagePack (быстрый, компактный, схема-free)
- Формат сообщения: `{method: str, params: dict, request_id: str}`
- Используется для:
  - Координации задач (назначение, статусы)
  - Запроса конкретных шардов памяти
  - Агент-к-агенту диалогов

## Слой 2: Распределённая память

### Модель данных — MemoryBlock

```python
@dataclass
class MemoryBlock:
    id: str              # UUID4
    owner_id: str        # Node ID автора
    block_type: str      # "dialog" | "task_result" | "knowledge"
    content: bytes       # Сериализованные данные (msgpack)
    timestamp: float     # Unix timestamp создания
    ttl: int | None      # Время жизни в секундах (None = бессмертный)
    tags: list[str]      # Теги для поиска
```

### Reed-Solomon шардинг

- Параметры: k=4 data shards + m=2 parity shards = 6 всего
- Гарантия: любые 4 из 6 шардов восстанавливают блок целиком
- Допустимые потери: до 2 шардов (33% нод) без потери данных
- Распределение: каждый шард отправляется на отдельную ноду (выбор по XOR-расстоянию в Kademlia)
- Библиотека: `reedsolo`

### API слоя памяти

```python
class DistributedMemory:
    async def store(self, block: MemoryBlock) -> str:
        """Шардит блок через Reed-Solomon, раздаёт шарды по нодам.
        Возвращает block_id. Metadata (block_id -> shard locations)
        сохраняется в DHT."""

    async def retrieve(self, block_id: str) -> MemoryBlock:
        """Находит shard locations в DHT, собирает минимум k шардов,
        восстанавливает блок через RS-декодинг."""

    async def search(self, tags: list[str], owner: str | None = None) -> list[MemoryBlock]:
        """Поиск по тегам. Индекс тегов хранится в DHT:
        tag -> list[block_id]. Опционально фильтр по owner."""

    async def delete(self, block_id: str) -> bool:
        """Удаляет шарды с нод-хранителей и metadata из DHT."""
```

### Self-healing (самовосстановление)

- Каждые 60 сек: нода проверяет здоровье шардов, за которые отвечает (PING хранителям)
- При обнаружении мёртвой ноды-хранителя:
  1. Оставшиеся шарды используются для восстановления недостающего
  2. Восстановленный шард перемещается на новую живую ноду
- Gossip-канал: быстрое оповещение всей сети о смерти ноды (не ждём 60 сек)

## Слой 3: ИИ-агенты

### Базовый класс агента

```python
class SwarmAgent:
    node_id: str
    memory: DistributedMemory
    llm: LLMRouter
    skills: dict[str, Skill]
    task_queue: asyncio.Queue

    async def run(self):
        """Основной цикл:
        1. Слушать Gossip на TASK_BROADCAST
        2. Проверять task_queue
        3. Выполнять задачу с помощью skills + llm
        4. Сохранять результат в memory
        5. Оповестить координатора через RPC"""

    async def think(self, context: str, system_prompt: str = None) -> str:
        """Вызов LLM с контекстом. Автоматически подтягивает
        релевантные блоки из памяти."""

    async def delegate(self, task: Task, target_node: str | None = None):
        """Отдать подзадачу: если target указан — через RPC,
        иначе — бродкаст через Gossip."""
```

### Жизненный цикл задачи

1. **Ввод:** Человек отправляет цель через CLI (`python node.py task "..."`)
2. **Координация:** Принявшая нода становится координатором, вызывает LLM для декомпозиции
3. **Рассылка:** Подзадачи бродкастятся через Gossip (тип `TASK_BROADCAST`)
4. **Захват:** Агенты сами берут подзадачи (first-come-first-served, подтверждение через RPC координатору)
5. **Выполнение:** Агент использует skills + LLM для решения подзадачи
6. **Сохранение:** Результат сохраняется в distributed memory
7. **Сборка:** Координатор получает RPC-уведомления о готовности, собирает финальный ответ

### Навыки (Skills) — MVP

**WebParserSkill:**
- Принимает URL + инструкцию что извлечь
- Использует `httpx` для загрузки + `selectolax` для парсинга HTML
- LLM помогает структурировать извлечённые данные

**ChatSkill:**
- Агент-к-агенту диалог для обсуждения задач
- Сообщения идут через RPC
- История сохраняется в distributed memory (block_type="dialog")

## Слой 4: LLM (OpenRouter)

### Key Pool

```python
@dataclass
class APIKey:
    key: str
    requests_made: int = 0
    last_error: float | None = None
    cooldown_until: float | None = None

class KeyPool:
    keys: list[APIKey]

    def get_key(self) -> APIKey:
        """Round-robin среди доступных ключей.
        Пропускает ключи в cooldown."""

    def mark_failed(self, key: APIKey, cooldown_seconds: int = 60):
        """Ставит ключ на cooldown после ошибки."""

    def mark_success(self, key: APIKey):
        """Сбрасывает счётчик ошибок."""
```

### LLM Router

```python
class LLMRouter:
    key_pool: KeyPool
    models: list[str]  # По приоритету

    async def complete(self, messages: list[dict], model: str | None = None) -> str:
        """Отправляет запрос в OpenRouter.
        - Если model не указан — берёт первый из списка
        - При ошибке/таймауте — fallback на следующую модель
        - Retry: exponential backoff (1s -> 2s -> 4s), max 3 попытки на модель
        """
```

**Цепочка моделей (по приоритету):**
1. `anthropic/claude-sonnet-4-20250514` — основная
2. `x-ai/grok-3` — первый резерв
3. `meta-llama/llama-3.3-70b-instruct` — бесплатный fallback

### Конфигурация

```yaml
llm:
  base_url: "https://openrouter.ai/api/v1"
  keys:
    - "sk-or-key1..."
    - "sk-or-key2..."
  models:
    - "anthropic/claude-sonnet-4-20250514"
    - "x-ai/grok-3"
    - "meta-llama/llama-3.3-70b-instruct"
  timeout: 30
  max_retries: 3
```

## Слой 5: CLI и запуск

### Запуск нод

```bash
# Первая нода (bootstrap)
python node.py --port 8000

# Дополнительные ноды
python node.py --port 8001 --bootstrap localhost:8000
python node.py --port 8002 --bootstrap localhost:8000
```

### Управление

```bash
python node.py task "Спарси цены на лобовые стёкла с autoglass.ru"
python node.py status           # Статус сети (кол-во нод, задач)
python node.py nodes            # Список живых нод с пингами
python node.py memory search "автостёкла"  # Поиск в памяти по тегам
```

CLI реализован через `click`.

## Зависимости

```
kademlia>=2.2.2       # DHT implementation (asyncio)
reedsolo>=1.7.0       # Reed-Solomon erasure coding
msgpack>=1.0.0        # Fast serialization for RPC
httpx>=0.27.0         # Async HTTP (LLM + parsing)
selectolax>=0.3.0     # Fast HTML parsing (Modest engine)
pyyaml>=6.0           # Config loading
click>=8.0            # CLI framework
```

## Тестовые сценарии

1. **P2P Discovery:** Запуск 3-5 нод, проверка что все находят друг друга через Kademlia
2. **Gossip Propagation:** Отправить сообщение на одну ноду, проверить что все получили за <10 сек
3. **Memory Resilience:** Сохранить блок, убить 2 из 6 нод-хранителей, проверить восстановление
4. **Task Decomposition:** Отправить "спарси цены с 3 сайтов", проверить что агенты разобрали и выполнили
5. **Agent Chat:** Два агента обсуждают тему, диалог сохраняется в distributed memory

## Стратегия деплоя

- **Фаза 1:** Локально (несколько процессов, разные порты)
- **Фаза 2:** LAN (несколько машин в одной сети)
- **Фаза 3:** Интернет (VPS, NAT traversal — TBD)

## Безопасность

- **Фаза 1:** Trust-all (нет аутентификации, все ноды доверяют друг другу)
- **Будущее:** Ed25519 идентификация нод, шифрование каналов, система репутации

## Ограничения MVP

- Нет персистентности: при перезапуске ноды данные теряются (только in-memory)
- Нет NAT traversal: работает только в LAN или с проброшенными портами
- Нет лимита на размер блока памяти (потенциально OOM при больших данных)
- Координатор — единая точка отказа для конкретной задачи (но не для сети)
