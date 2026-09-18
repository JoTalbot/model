# Multi-Agent Chat — Design Spec

## Overview

Мультиагентный групповой чат для "Бессмертного Роя". Три бизнес-агента (парсер цен, аналитик рынка, менеджер по закупкам) общаются в общей "комнате", решая задачи по автостёклам.

## Architecture: ChatRoom Pattern

Единая ChatRoom хранит shared context (историю сообщений). LLM-based Selector решает, кто говорит следующим. Каждый агент видит полную историю + свой system prompt.

## Configuration

```yaml
agents:
  - name: "parser"
    role: "Парсер цен на автостёкла"
    model: "meta-llama/llama-3.3-70b-instruct"
    system_prompt: |
      Ты — агент-парсер. Твоя задача: находить и извлекать цены 
      на автостёкла из веб-источников. Отвечай структурированно.

  - name: "analyst"
    role: "Аналитик рынка автостёкол"
    model: "anthropic/claude-sonnet-4-20250514"
    system_prompt: |
      Ты — аналитик рынка. Анализируй данные от парсера, 
      сравнивай цены, выявляй тренды и выгодные предложения.

  - name: "manager"
    role: "Менеджер по закупкам"
    model: "x-ai/grok-3"
    system_prompt: |
      Ты — менеджер по закупкам для магазина автостёкол.
      Принимай решения о закупках на основе анализа рынка.

chat:
  max_rounds: 15
  max_tokens_per_agent: 2000
  selector: "llm"
  done_keyword: "[DONE]"
```

### Config Semantics

- `agents[].model` — модель OpenRouter для этого агента
- `chat.max_rounds` — жёсткий лимит раундов (страховка от бесконечного чата)
- `chat.selector` — `"llm"` (LLM выбирает кто говорит) или `"round_robin"` (по кругу)
- `chat.done_keyword` — маркер завершения; если агент включает его в ответ, чат заканчивается
- Все агенты используют общий `KeyPool` из секции `llm.keys`

## Data Structures

```python
@dataclass
class ChatMessage:
    agent_name: str
    role: str
    content: str
    round_num: int
    timestamp: float

@dataclass
class ChatResult:
    messages: list[ChatMessage]
    rounds_used: int
    finished_naturally: bool   # True = агент сказал [DONE]
    summary: str              # последнее сообщение или LLM-summary
```

## Components

### AgentParticipant (`swarm/chat/participant.py`)

Обёртка над LLMRouter для одного участника чата.

```python
class AgentParticipant:
    name: str
    role: str
    system_prompt: str
    llm: LLMRouter  # настроен на конкретную модель

    async def respond(self, messages: list[ChatMessage]) -> str
```

- `respond()` формирует prompt из system_prompt + история сообщений
- Возвращает текст ответа агента
- Каждый AgentParticipant получает собственный LLMRouter с указанной моделью, но общий KeyPool

### Selector (`swarm/chat/selector.py`)

Решает, кто говорит следующим.

```python
class LLMSelector:
    async def select(self, agents: list[str], messages: list[ChatMessage]) -> str

class RoundRobinSelector:
    def select(self, agents: list[str], messages: list[ChatMessage]) -> str
```

**LLMSelector:**
- Использует дешёвую модель (первую из `llm.models`)
- Prompt: "Given these agents and recent conversation, who should speak next? Return ONLY the agent name."
- Передаёт список агентов + последние 3 сообщения
- Fallback: если LLM вернул невалидное имя → round-robin

**RoundRobinSelector:**
- Простой циклический перебор агентов

### ChatRoom (`swarm/chat/room.py`)

Основной движок.

```python
class ChatRoom:
    def __init__(self, participants, selector, config): ...
    
    async def run(self, goal: str) -> ChatResult
    async def step(self) -> ChatMessage | None
```

**`run(goal)` flow:**
1. Создаёт начальное сообщение: `ChatMessage(agent_name="user", content=goal)`
2. Цикл (до `max_rounds`):
   a. Selector выбирает агента
   b. Агент вызывает `respond(messages)` → получает ответ
   c. Добавляет `ChatMessage` в историю
   d. Если `done_keyword` в ответе → break
3. Формирует `ChatResult`

**`step()`** — для интерактивного режима (шаг за шагом, с выводом в реальном времени).

### CLI Display (`swarm/chat/cli_display.py`)

Цветной вывод в терминал.

```python
class ChatDisplay:
    def show_message(self, msg: ChatMessage) -> None
    def show_result(self, result: ChatResult) -> None
    def show_goal(self, goal: str) -> None
```

- Каждый агент получает свой цвет (из палитры: зелёный, синий, жёлтый, красный...)
- Иконки по ролям: 🔍 парсер, 📊 аналитик, 💼 менеджер
- Итог выделяется визуально

## CLI Commands

### `python node.py chat`

Интерактивный режим:
1. Показывает список доступных агентов
2. Запрашивает задачу от пользователя
3. Запускает ChatRoom.run() с real-time выводом через step()
4. По завершении показывает итог и спрашивает новую задачу
5. `exit` или Ctrl+C — выход

### `python node.py task "описание" [--agents parser,analyst] [--json]`

Одноразовая команда:
- `--agents` — ограничить список участников (по умолчанию все)
- `--json` — вывести результат в JSON-формате
- Без флагов — человекочитаемый вывод итога

## File Structure

```
swarm/chat/
├── __init__.py
├── room.py          # ChatRoom, ChatMessage, ChatResult
├── selector.py      # LLMSelector, RoundRobinSelector
├── participant.py   # AgentParticipant
└── cli_display.py   # Цветной вывод
```

**Изменяемые файлы:**
- `config.yaml` — секции `agents` и `chat`
- `node.py` — команды `chat`, обновлённая `task`

**Не изменяются:**
- `swarm/llm/` — используем LLMRouter/KeyPool as-is
- `swarm/agent/` — ChatRoom не зависит от SwarmAgent
- `swarm/network/` — P2P слой подключим позже для распределённого чата

## Error Handling

- **LLM timeout / error** → retry через LLMRouter (уже реализовано), если все модели failed → пропускаем ход агента, логируем warning
- **Invalid selector response** → fallback на round-robin для этого раунда
- **Empty agent response** → пропускаем, инкрементируем раунд
- **Config: no keys** → ошибка при старте: "Add OpenRouter keys to config.yaml"
- **Config: no agents** → ошибка: "Define at least one agent in config.yaml"

## Testing Strategy

- Unit tests: Selector (LLM mock), AgentParticipant (LLM mock), ChatRoom (full mock)
- Integration test: реальный чат с 2 mock-агентами, проверяем flow и termination
- CLI tests: click.testing.CliRunner для команд `chat` и `task`

## Future: Distribution

ChatRoom сейчас работает in-process. Для распределения:
- Каждый AgentParticipant → отдельная нода
- Messages синхронизируются через Gossip
- Selector может быть на любой ноде (или каждая нода запускает своего)

Это изменение локализовано в `participant.py` (вызов LLM → RPC к удалённому агенту).
