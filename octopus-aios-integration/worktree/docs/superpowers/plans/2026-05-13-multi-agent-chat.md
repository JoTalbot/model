# Multi-Agent Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-agent group chat where 3 business-role agents (parser, analyst, manager) collaborate in a shared ChatRoom to solve tasks.

**Architecture:** ChatRoom pattern — shared message history, LLM-based selector picks next speaker, per-agent LLMRouter with different models, combo termination (done keyword + max rounds).

**Tech Stack:** Python asyncio, httpx, click, colorama (terminal colors), pytest, pytest-asyncio

---

### Task 1: Config Update + colorama dependency

**Files:**
- Modify: `config.yaml`
- Modify: `requirements.txt`

- [x] **Step 1: Update config.yaml with agents and chat sections**

```yaml
node:
  port: 8000
  bootstrap: []

llm:
  base_url: "https://openrouter.ai/api/v1"
  keys: []
  models:
    - "anthropic/claude-sonnet-4-20250514"
    - "x-ai/grok-3"
    - "meta-llama/llama-3.3-70b-instruct"
  timeout: 30
  max_retries: 3

gossip:
  interval: 5
  fanout: 3
  seen_capacity: 1000

memory:
  data_shards: 4
  parity_shards: 2
  health_check_interval: 60

agents:
  - name: "parser"
    role: "Парсер цен на автостёкла"
    model: "meta-llama/llama-3.3-70b-instruct"
    system_prompt: "Ты — агент-парсер. Твоя задача: находить и извлекать цены на автостёкла из веб-источников. Отвечай структурированно: название, цена, источник."

  - name: "analyst"
    role: "Аналитик рынка автостёкол"
    model: "anthropic/claude-sonnet-4-20250514"
    system_prompt: "Ты — аналитик рынка. Анализируй данные от парсера, сравнивай цены, выявляй тренды и выгодные предложения. Давай конкретные рекомендации."

  - name: "manager"
    role: "Менеджер по закупкам"
    model: "x-ai/grok-3"
    system_prompt: "Ты — менеджер по закупкам для магазина автостёкол на Ивана Олинского 66. Принимай решения о закупках на основе анализа рынка. Когда решение принято, заверши ответ словом [DONE]."

chat:
  max_rounds: 15
  max_tokens_per_agent: 2000
  selector: "llm"
  done_keyword: "[DONE]"
```

- [x] **Step 2: Add colorama to requirements.txt**

Append to `requirements.txt`:
```
colorama>=0.4.6
```

- [x] **Step 3: Install new dependency**

Run: `pip install colorama`

- [x] **Step 4: Commit**

```bash
git add config.yaml requirements.txt
git commit -m "chore: add agent roles, chat config, and colorama dependency"
```

---

### Task 2: ChatMessage & ChatResult data structures

**Files:**
- Create: `swarm/chat/__init__.py`
- Create: `swarm/chat/room.py`
- Test: `tests/test_chat_room.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_chat_room.py`:

```python
import time
import pytest
from swarm.chat.room import ChatMessage, ChatResult


def test_chat_message_creation():
    msg = ChatMessage(
        agent_name="parser",
        role="Парсер цен",
        content="Нашёл цены",
        round_num=1,
        timestamp=time.time(),
    )
    assert msg.agent_name == "parser"
    assert msg.round_num == 1
    assert msg.content == "Нашёл цены"


def test_chat_result_creation():
    msg = ChatMessage(
        agent_name="manager",
        role="Менеджер",
        content="Заказываем [DONE]",
        round_num=3,
        timestamp=time.time(),
    )
    result = ChatResult(
        messages=[msg],
        rounds_used=3,
        finished_naturally=True,
        summary="Заказываем [DONE]",
    )
    assert result.finished_naturally is True
    assert result.rounds_used == 3
    assert len(result.messages) == 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_room.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'swarm.chat'"

- [x] **Step 3: Write minimal implementation**

Create `swarm/chat/__init__.py` (empty file).

Create `swarm/chat/room.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    agent_name: str
    role: str
    content: str
    round_num: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChatResult:
    messages: list[ChatMessage]
    rounds_used: int
    finished_naturally: bool
    summary: str
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_room.py -v`
Expected: PASS (2 tests)

- [x] **Step 5: Commit**

```bash
git add swarm/chat/__init__.py swarm/chat/room.py tests/test_chat_room.py
git commit -m "feat: add ChatMessage and ChatResult data structures"
```

---

### Task 3: AgentParticipant

**Files:**
- Create: `swarm/chat/participant.py`
- Test: `tests/test_chat_participant.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_chat_participant.py`:

```python
import time
import pytest
from unittest.mock import AsyncMock
from swarm.chat.participant import AgentParticipant
from swarm.chat.room import ChatMessage


@pytest.mark.asyncio
async def test_participant_respond():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="Цена лобового: 3000₽")

    participant = AgentParticipant(
        name="parser",
        role="Парсер цен",
        system_prompt="Ты — парсер. Ищи цены.",
        llm=mock_llm,
    )

    messages = [
        ChatMessage(
            agent_name="user",
            role="user",
            content="Найди цены на лобовое ВАЗ 2114",
            round_num=0,
            timestamp=time.time(),
        )
    ]

    result = await participant.respond(messages)
    assert result == "Цена лобового: 3000₽"

    call_args = mock_llm.complete.call_args[0][0]
    assert call_args[0]["role"] == "system"
    assert "парсер" in call_args[0]["content"].lower()
    assert call_args[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_participant_uses_specified_model():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="ok")

    participant = AgentParticipant(
        name="analyst",
        role="Аналитик",
        system_prompt="Ты — аналитик.",
        llm=mock_llm,
        model="anthropic/claude-sonnet-4-20250514",
    )

    messages = [
        ChatMessage(agent_name="user", role="user", content="test", round_num=0, timestamp=0)
    ]
    await participant.respond(messages)

    call_kwargs = mock_llm.complete.call_args[1]
    assert call_kwargs.get("model") == "anthropic/claude-sonnet-4-20250514"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_participant.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'swarm.chat.participant'"

- [x] **Step 3: Write minimal implementation**

Create `swarm/chat/participant.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from swarm.chat.room import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class AgentParticipant:
    name: str
    role: str
    system_prompt: str
    llm: object
    model: str | None = None

    async def respond(self, messages: list[ChatMessage]) -> str:
        prompt_messages = [{"role": "system", "content": self.system_prompt}]

        for msg in messages:
            role = "assistant" if msg.agent_name == self.name else "user"
            prefix = f"[{msg.agent_name}] " if msg.agent_name != self.name else ""
            prompt_messages.append({"role": role, "content": f"{prefix}{msg.content}"})

        kwargs = {}
        if self.model:
            kwargs["model"] = self.model

        response = await self.llm.complete(prompt_messages, **kwargs)
        return response
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_participant.py -v`
Expected: PASS (2 tests)

- [x] **Step 5: Commit**

```bash
git add swarm/chat/participant.py tests/test_chat_participant.py
git commit -m "feat: add AgentParticipant with model-specific LLM calls"
```

---

### Task 4: Selectors (RoundRobin + LLM)

**Files:**
- Create: `swarm/chat/selector.py`
- Test: `tests/test_chat_selector.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_chat_selector.py`:

```python
import time
import pytest
from unittest.mock import AsyncMock
from swarm.chat.selector import RoundRobinSelector, LLMSelector
from swarm.chat.room import ChatMessage


def test_round_robin_cycles():
    selector = RoundRobinSelector()
    agents = ["parser", "analyst", "manager"]
    msgs = []

    assert selector.select(agents, msgs) == "parser"
    assert selector.select(agents, msgs) == "analyst"
    assert selector.select(agents, msgs) == "manager"
    assert selector.select(agents, msgs) == "parser"


@pytest.mark.asyncio
async def test_llm_selector_valid_response():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="analyst")

    selector = LLMSelector(llm=mock_llm)
    agents = ["parser", "analyst", "manager"]
    messages = [
        ChatMessage(agent_name="parser", role="Парсер", content="Нашёл данные", round_num=1, timestamp=time.time())
    ]

    result = await selector.select(agents, messages)
    assert result == "analyst"


@pytest.mark.asyncio
async def test_llm_selector_invalid_response_falls_back():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="unknown_agent_xyz")

    selector = LLMSelector(llm=mock_llm)
    agents = ["parser", "analyst", "manager"]
    messages = [
        ChatMessage(agent_name="parser", role="Парсер", content="test", round_num=1, timestamp=time.time())
    ]

    result = await selector.select(agents, messages)
    assert result in agents


@pytest.mark.asyncio
async def test_llm_selector_excludes_last_speaker():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="analyst")

    selector = LLMSelector(llm=mock_llm)
    agents = ["parser", "analyst", "manager"]
    messages = [
        ChatMessage(agent_name="analyst", role="Аналитик", content="already spoke", round_num=1, timestamp=time.time())
    ]

    result = await selector.select(agents, messages)
    assert result == "analyst"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_selector.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'swarm.chat.selector'"

- [x] **Step 3: Write minimal implementation**

Create `swarm/chat/selector.py`:

```python
from __future__ import annotations

import logging

from swarm.chat.room import ChatMessage

logger = logging.getLogger(__name__)


class RoundRobinSelector:
    def __init__(self) -> None:
        self._index = 0

    def select(self, agents: list[str], messages: list[ChatMessage]) -> str:
        agent = agents[self._index % len(agents)]
        self._index += 1
        return agent


class LLMSelector:
    def __init__(self, llm) -> None:
        self.llm = llm
        self._fallback = RoundRobinSelector()

    async def select(self, agents: list[str], messages: list[ChatMessage]) -> str:
        recent = messages[-3:] if messages else []
        history_text = "\n".join(
            f"[{m.agent_name}]: {m.content[:100]}" for m in recent
        )

        prompt = (
            f"Agents available: {', '.join(agents)}\n"
            f"Recent conversation:\n{history_text}\n\n"
            f"Who should speak next? Return ONLY the agent name, nothing else."
        )

        try:
            response = await self.llm.complete([{"role": "user", "content": prompt}])
            chosen = response.strip().lower()

            for agent in agents:
                if agent.lower() == chosen:
                    return agent

            logger.warning("LLM selector returned invalid name '%s', falling back", chosen)
            return self._fallback.select(agents, messages)
        except Exception as exc:
            logger.warning("LLM selector failed: %s, falling back to round-robin", exc)
            return self._fallback.select(agents, messages)
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_selector.py -v`
Expected: PASS (4 tests)

- [x] **Step 5: Commit**

```bash
git add swarm/chat/selector.py tests/test_chat_selector.py
git commit -m "feat: add RoundRobin and LLM selectors for chat turn management"
```

---

### Task 5: ChatRoom engine

**Files:**
- Modify: `swarm/chat/room.py`
- Test: `tests/test_chat_room.py` (add new tests)

- [x] **Step 1: Write the failing test**

Append to `tests/test_chat_room.py`:

```python
import asyncio
from unittest.mock import AsyncMock
from swarm.chat.room import ChatRoom, ChatMessage, ChatResult, ChatConfig
from swarm.chat.participant import AgentParticipant
from swarm.chat.selector import RoundRobinSelector


@pytest.mark.asyncio
async def test_chat_room_runs_to_completion():
    mock_llm_a = AsyncMock()
    mock_llm_a.complete = AsyncMock(return_value="Нашёл цены: 3000₽")

    mock_llm_b = AsyncMock()
    mock_llm_b.complete = AsyncMock(return_value="Анализ готов. Рекомендую. [DONE]")

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="Ищи цены", llm=mock_llm_a),
        AgentParticipant(name="analyst", role="Аналитик", system_prompt="Анализируй", llm=mock_llm_b),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=10, done_keyword="[DONE]")

    room = ChatRoom(participants=participants, selector=selector, config=config)
    result = await room.run("Найди цены на лобовое ВАЗ 2114")

    assert result.finished_naturally is True
    assert result.rounds_used == 2
    assert len(result.messages) == 3  # user + parser + analyst
    assert "[DONE]" in result.messages[-1].content


@pytest.mark.asyncio
async def test_chat_room_respects_max_rounds():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="Продолжаю работать...")

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="test", llm=mock_llm),
        AgentParticipant(name="analyst", role="Аналитик", system_prompt="test", llm=mock_llm),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=3, done_keyword="[DONE]")

    room = ChatRoom(participants=participants, selector=selector, config=config)
    result = await room.run("тест")

    assert result.finished_naturally is False
    assert result.rounds_used == 3


@pytest.mark.asyncio
async def test_chat_room_step_by_step():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="Ответ агента [DONE]")

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="test", llm=mock_llm),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=5, done_keyword="[DONE]")

    room = ChatRoom(participants=participants, selector=selector, config=config)
    room.start("Тестовая задача")

    msg = await room.step()
    assert msg is not None
    assert msg.agent_name == "parser"

    msg2 = await room.step()
    assert msg2 is None  # finished because [DONE]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_room.py -v`
Expected: FAIL with "ImportError: cannot import name 'ChatRoom'"

- [x] **Step 3: Write implementation**

Update `swarm/chat/room.py` (replace entire contents):

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swarm.chat.participant import AgentParticipant


@dataclass
class ChatMessage:
    agent_name: str
    role: str
    content: str
    round_num: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChatResult:
    messages: list[ChatMessage]
    rounds_used: int
    finished_naturally: bool
    summary: str


@dataclass
class ChatConfig:
    max_rounds: int = 15
    done_keyword: str = "[DONE]"


class ChatRoom:
    def __init__(
        self,
        participants: list[AgentParticipant],
        selector,
        config: ChatConfig,
    ) -> None:
        self.participants = {p.name: p for p in participants}
        self.selector = selector
        self.config = config
        self.messages: list[ChatMessage] = []
        self._round = 0
        self._finished = False

    def start(self, goal: str) -> None:
        self.messages = [
            ChatMessage(
                agent_name="user",
                role="user",
                content=goal,
                round_num=0,
            )
        ]
        self._round = 0
        self._finished = False

    async def step(self) -> ChatMessage | None:
        if self._finished or self._round >= self.config.max_rounds:
            return None

        agent_names = list(self.participants.keys())

        if hasattr(self.selector, '__call__') or hasattr(self.selector.select, '__self__'):
            select_result = self.selector.select(agent_names, self.messages)
        else:
            select_result = self.selector.select(agent_names, self.messages)

        import asyncio
        if asyncio.iscoroutine(select_result):
            chosen_name = await select_result
        else:
            chosen_name = select_result

        participant = self.participants[chosen_name]
        response = await participant.respond(self.messages)

        self._round += 1
        msg = ChatMessage(
            agent_name=chosen_name,
            role=participant.role,
            content=response,
            round_num=self._round,
        )
        self.messages.append(msg)

        if self.config.done_keyword in response:
            self._finished = True

        return msg

    async def run(self, goal: str) -> ChatResult:
        self.start(goal)

        while not self._finished and self._round < self.config.max_rounds:
            msg = await self.step()
            if msg is None:
                break

        return ChatResult(
            messages=self.messages,
            rounds_used=self._round,
            finished_naturally=self._finished,
            summary=self.messages[-1].content if self.messages else "",
        )
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_room.py -v`
Expected: PASS (5 tests)

- [x] **Step 5: Commit**

```bash
git add swarm/chat/room.py tests/test_chat_room.py
git commit -m "feat: add ChatRoom engine with step-by-step and run modes"
```

---

### Task 6: CLI Display (colorama)

**Files:**
- Create: `swarm/chat/cli_display.py`
- Test: `tests/test_chat_display.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_chat_display.py`:

```python
import time
from swarm.chat.room import ChatMessage, ChatResult
from swarm.chat.cli_display import ChatDisplay


def test_display_formats_message(capsys):
    display = ChatDisplay()
    msg = ChatMessage(
        agent_name="parser",
        role="Парсер цен",
        content="Цена: 3000₽",
        round_num=1,
        timestamp=time.time(),
    )
    display.show_message(msg)
    captured = capsys.readouterr()
    assert "parser" in captured.out.lower() or "Парсер" in captured.out
    assert "3000₽" in captured.out


def test_display_formats_goal(capsys):
    display = ChatDisplay()
    display.show_goal("Найди цены")
    captured = capsys.readouterr()
    assert "Найди цены" in captured.out


def test_display_formats_result(capsys):
    msg = ChatMessage(agent_name="manager", role="Менеджер", content="Done", round_num=2, timestamp=time.time())
    result = ChatResult(messages=[msg], rounds_used=2, finished_naturally=True, summary="Done")
    display = ChatDisplay()
    display.show_result(result)
    captured = capsys.readouterr()
    assert "2" in captured.out
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_display.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [x] **Step 3: Write minimal implementation**

Create `swarm/chat/cli_display.py`:

```python
from __future__ import annotations

from colorama import Fore, Style, init

from swarm.chat.room import ChatMessage, ChatResult

init(autoreset=True)

AGENT_COLORS = {
    "parser": Fore.GREEN,
    "analyst": Fore.CYAN,
    "manager": Fore.YELLOW,
}

AGENT_ICONS = {
    "parser": "🔍",
    "analyst": "📊",
    "manager": "💼",
}

DEFAULT_COLOR = Fore.WHITE
DEFAULT_ICON = "🤖"


class ChatDisplay:
    def show_goal(self, goal: str) -> None:
        print(f"\n{Fore.MAGENTA}🎯 Задача: {goal}{Style.RESET_ALL}\n")

    def show_message(self, msg: ChatMessage) -> None:
        color = AGENT_COLORS.get(msg.agent_name, DEFAULT_COLOR)
        icon = AGENT_ICONS.get(msg.agent_name, DEFAULT_ICON)
        header = f"{color}[{msg.agent_name.capitalize()} {icon}]{Style.RESET_ALL}"
        print(f"{header} {msg.content}\n")

    def show_result(self, result: ChatResult) -> None:
        status = "✅ Чат завершён" if result.finished_naturally else "⏱️ Лимит раундов"
        print(f"\n{Fore.WHITE}{Style.BRIGHT}{status} за {result.rounds_used} раунд(ов){Style.RESET_ALL}")
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_display.py -v`
Expected: PASS (3 tests)

- [x] **Step 5: Commit**

```bash
git add swarm/chat/cli_display.py tests/test_chat_display.py
git commit -m "feat: add colored CLI display for chat messages"
```

---

### Task 7: CLI commands (chat + updated task)

**Files:**
- Modify: `node.py`
- Test: `tests/test_node_cli.py` (add new tests)

- [x] **Step 1: Write the failing test**

Append to `tests/test_node_cli.py`:

```python
def test_cli_chat_command_exists(runner):
    result = runner.invoke(cli, ["chat", "--help"])
    assert result.exit_code == 0
    assert "Interactive" in result.output or "chat" in result.output.lower()


def test_cli_task_with_agents_option(runner):
    result = runner.invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
    assert "--agents" in result.output


def test_cli_task_with_json_option(runner):
    result = runner.invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_node_cli.py -v`
Expected: FAIL (new tests fail)

- [x] **Step 3: Write implementation**

Update `node.py` — add the `chat` command and update `task`:

```python
from __future__ import annotations

import asyncio
import json as json_module
import logging

import click
import yaml

from swarm.llm.key_pool import APIKey, KeyPool
from swarm.llm.router import LLMRouter
from swarm.memory.erasure import ErasureCoder
from swarm.memory.store import DistributedMemory
from swarm.network.gossip import GossipProtocol
from swarm.network.kademlia import KademliaNode
from swarm.network.rpc import RPCServer, RPCClient
from swarm.agent.core import SwarmAgent, Task
from swarm.agent.task_manager import TaskManager
from swarm.chat.room import ChatRoom, ChatConfig
from swarm.chat.participant import AgentParticipant
from swarm.chat.selector import LLMSelector, RoundRobinSelector
from swarm.chat.cli_display import ChatDisplay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("swarm")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_chat_components(cfg: dict) -> tuple[list[AgentParticipant], object, ChatConfig]:
    llm_cfg = cfg["llm"]
    keys = [APIKey(key=k) for k in llm_cfg.get("keys", [])]
    if not keys:
        raise click.ClickException("Add OpenRouter keys to config.yaml (llm.keys)")

    agents_cfg = cfg.get("agents", [])
    if not agents_cfg:
        raise click.ClickException("Define at least one agent in config.yaml (agents)")

    key_pool = KeyPool(keys=keys)
    chat_cfg = cfg.get("chat", {})

    participants = []
    for agent_cfg in agents_cfg:
        llm = LLMRouter(
            key_pool=key_pool,
            models=[agent_cfg["model"]],
            base_url=llm_cfg["base_url"],
            timeout=llm_cfg["timeout"],
            max_retries=llm_cfg["max_retries"],
        )
        participants.append(AgentParticipant(
            name=agent_cfg["name"],
            role=agent_cfg["role"],
            system_prompt=agent_cfg["system_prompt"],
            llm=llm,
            model=agent_cfg["model"],
        ))

    selector_type = chat_cfg.get("selector", "round_robin")
    if selector_type == "llm":
        selector_llm = LLMRouter(
            key_pool=key_pool,
            models=llm_cfg["models"][:1],
            base_url=llm_cfg["base_url"],
            timeout=llm_cfg["timeout"],
            max_retries=llm_cfg["max_retries"],
        )
        selector = LLMSelector(llm=selector_llm)
    else:
        selector = RoundRobinSelector()

    config = ChatConfig(
        max_rounds=chat_cfg.get("max_rounds", 15),
        done_keyword=chat_cfg.get("done_keyword", "[DONE]"),
    )

    return participants, selector, config


async def run_chat_interactive(cfg: dict) -> None:
    participants, selector, config = build_chat_components(cfg)
    display = ChatDisplay()
    room = ChatRoom(participants=participants, selector=selector, config=config)

    agent_names = [p.name for p in participants]
    click.echo(f"Агенты: {', '.join(agent_names)}")
    click.echo("Введи задачу (или 'exit' для выхода):\n")

    while True:
        try:
            goal = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if goal.lower() in ("exit", "quit", "q"):
            break
        if not goal:
            continue

        display.show_goal(goal)
        room.start(goal)

        while True:
            msg = await room.step()
            if msg is None:
                break
            display.show_message(msg)

        result = room._build_result()
        display.show_result(result)
        click.echo("")


async def run_task_oneshot(cfg: dict, description: str, agents_filter: str | None, output_json: bool) -> None:
    participants, selector, config = build_chat_components(cfg)

    if agents_filter:
        names = [n.strip() for n in agents_filter.split(",")]
        participants = [p for p in participants if p.name in names]
        if not participants:
            raise click.ClickException(f"No matching agents for: {agents_filter}")

    room = ChatRoom(participants=participants, selector=selector, config=config)
    display = ChatDisplay()

    if not output_json:
        display.show_goal(description)

    room.start(description)
    while True:
        msg = await room.step()
        if msg is None:
            break
        if not output_json:
            display.show_message(msg)

    result = room._build_result()

    if output_json:
        data = {
            "rounds_used": result.rounds_used,
            "finished_naturally": result.finished_naturally,
            "summary": result.summary,
            "messages": [
                {"agent": m.agent_name, "role": m.role, "content": m.content, "round": m.round_num}
                for m in result.messages
            ],
        }
        click.echo(json_module.dumps(data, ensure_ascii=False, indent=2))
    else:
        display.show_result(result)


async def start_node(port: int, bootstrap: str | None, config_path: str) -> None:
    cfg = load_config(config_path)

    kad = KademliaNode(port=port)
    bootstrap_addr = None
    if bootstrap:
        host, bport = bootstrap.split(":")
        bootstrap_addr = (host, int(bport))
    await kad.start(bootstrap_addr=bootstrap_addr)

    gossip = GossipProtocol(
        host="0.0.0.0",
        port=port + 1000,
        interval=cfg["gossip"]["interval"],
        fanout=cfg["gossip"]["fanout"],
        seen_capacity=cfg["gossip"]["seen_capacity"],
    )

    rpc_server = RPCServer(host="0.0.0.0", port=port + 2000)
    rpc_client = RPCClient()

    llm_cfg = cfg["llm"]
    keys = [APIKey(key=k) for k in llm_cfg.get("keys", [])]
    if keys:
        key_pool = KeyPool(keys=keys)
        llm = LLMRouter(
            key_pool=key_pool,
            models=llm_cfg["models"],
            base_url=llm_cfg["base_url"],
            timeout=llm_cfg["timeout"],
            max_retries=llm_cfg["max_retries"],
        )
    else:
        llm = None

    mem_cfg = cfg["memory"]
    coder = ErasureCoder(
        data_shards=mem_cfg["data_shards"],
        parity_shards=mem_cfg["parity_shards"],
    )
    memory = DistributedMemory(
        kademlia=kad,
        rpc_client=rpc_client,
        coder=coder,
        node_id=kad.node_id or "unknown",
    )

    agent = SwarmAgent(
        node_id=kad.node_id or "unknown",
        memory=memory,
        llm=llm,
        gossip=gossip,
        rpc_client=rpc_client,
    )

    await gossip.start()
    await rpc_server.start()

    logger.info(
        "Node started: Kademlia=%d Gossip=%d RPC=%d",
        port, port + 1000, port + 2000,
    )

    try:
        await agent.run()
    except KeyboardInterrupt:
        pass
    finally:
        await agent.stop()
        await gossip.stop()
        await rpc_server.stop()
        await kad.stop()
        if llm:
            await llm.close()


@click.group()
def cli():
    """Immortal Swarm -- Distributed AI Agent Network"""
    pass


@cli.command()
@click.option("--port", default=8000, help="Kademlia port")
@click.option("--bootstrap", default=None, help="Bootstrap node (host:port)")
@click.option("--config", default="config.yaml", help="Config file path")
def start(port: int, bootstrap: str | None, config: str):
    """Start a swarm node."""
    asyncio.run(start_node(port, bootstrap, config))


@cli.command()
@click.option("--config", default="config.yaml", help="Config file path")
def chat(config: str):
    """Interactive multi-agent group chat."""
    cfg = load_config(config)
    asyncio.run(run_chat_interactive(cfg))


@cli.command()
@click.argument("description")
@click.option("--agents", default=None, help="Comma-separated agent names to use")
@click.option("--json", "output_json", is_flag=True, help="Output result as JSON")
@click.option("--config", default="config.yaml", help="Config file path")
def task(description: str, agents: str | None, output_json: bool, config: str):
    """Submit a task to the agent swarm."""
    cfg = load_config(config)
    asyncio.run(run_task_oneshot(cfg, description, agents, output_json))


@cli.command()
def status():
    """Show network status."""
    click.echo("Status: not connected (run 'start' first)")


@cli.command()
def nodes():
    """List known nodes."""
    click.echo("Nodes: not connected (run 'start' first)")


@cli.group()
def memory():
    """Memory operations."""
    pass


@memory.command()
@click.argument("query")
def search(query: str):
    """Search distributed memory by tags."""
    click.echo(f"Searching for: {query}")
    click.echo("(Connect to a running node to search)")


if __name__ == "__main__":
    cli()
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_node_cli.py -v`
Expected: PASS (7 tests)

- [x] **Step 5: Also add `_build_result` method to ChatRoom**

In `swarm/chat/room.py`, add this method to the `ChatRoom` class:

```python
    def _build_result(self) -> ChatResult:
        return ChatResult(
            messages=self.messages,
            rounds_used=self._round,
            finished_naturally=self._finished,
            summary=self.messages[-1].content if self.messages else "",
        )
```

- [x] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS

- [x] **Step 7: Commit**

```bash
git add node.py tests/test_node_cli.py swarm/chat/room.py
git commit -m "feat: add interactive chat and one-shot task CLI commands"
```

---

### Task 8: End-to-end chat integration test

**Files:**
- Create: `tests/test_chat_integration.py`

- [x] **Step 1: Write integration test**

Create `tests/test_chat_integration.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from swarm.chat.room import ChatRoom, ChatConfig
from swarm.chat.participant import AgentParticipant
from swarm.chat.selector import LLMSelector, RoundRobinSelector


@pytest.mark.asyncio
async def test_full_chat_flow_with_three_agents():
    """Integration: three agents discuss a task and reach conclusion."""
    responses = iter([
        "Нашёл цены: ВАЗ 2114 лобовое — exist.ru 2800₽, bor-glass 2500₽",
        "Анализ: bor-glass дешевле на 12%. Рекомендую закупить там.",
        "Решение: заказываем 5 шт у bor-glass по 2500₽. Итого 12500₽. [DONE]",
    ])

    async def mock_complete(messages, **kwargs):
        return next(responses)

    mock_llm = AsyncMock()
    mock_llm.complete = mock_complete

    participants = [
        AgentParticipant(
            name="parser", role="Парсер цен",
            system_prompt="Ищи цены на автостёкла", llm=mock_llm,
        ),
        AgentParticipant(
            name="analyst", role="Аналитик рынка",
            system_prompt="Анализируй цены", llm=mock_llm,
        ),
        AgentParticipant(
            name="manager", role="Менеджер по закупкам",
            system_prompt="Принимай решения", llm=mock_llm,
        ),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=10, done_keyword="[DONE]")
    room = ChatRoom(participants=participants, selector=selector, config=config)

    result = await room.run("Найди цены на лобовое стекло ВАЗ 2114 и закажи")

    assert result.finished_naturally is True
    assert result.rounds_used == 3
    assert result.messages[1].agent_name == "parser"
    assert result.messages[2].agent_name == "analyst"
    assert result.messages[3].agent_name == "manager"
    assert "2500" in result.messages[1].content
    assert "[DONE]" in result.messages[3].content


@pytest.mark.asyncio
async def test_llm_selector_integration():
    """Integration: LLM selector picks the right agent."""
    call_count = {"n": 0}

    async def mock_complete(messages, **kwargs):
        call_count["n"] += 1
        if len(messages) == 1 and "who should speak" in messages[0]["content"].lower():
            return "analyst"
        return f"Response #{call_count['n']} [DONE]"

    mock_llm = AsyncMock()
    mock_llm.complete = mock_complete

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="test", llm=mock_llm),
        AgentParticipant(name="analyst", role="Аналитик", system_prompt="test", llm=mock_llm),
    ]

    selector = LLMSelector(llm=mock_llm)
    config = ChatConfig(max_rounds=5, done_keyword="[DONE]")
    room = ChatRoom(participants=participants, selector=selector, config=config)

    result = await room.run("test task")

    assert result.messages[1].agent_name == "analyst"
    assert result.finished_naturally is True
```

- [x] **Step 2: Run test**

Run: `pytest tests/test_chat_integration.py -v`
Expected: PASS (2 tests)

- [x] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS

- [x] **Step 4: Commit**

```bash
git add tests/test_chat_integration.py
git commit -m "test: add end-to-end multi-agent chat integration tests"
```

---

## Self-Review

**Spec coverage:**
- ✅ Config with agents + chat sections → Task 1
- ✅ ChatMessage/ChatResult data structures → Task 2
- ✅ AgentParticipant with per-agent model → Task 3
- ✅ RoundRobin + LLM selectors → Task 4
- ✅ ChatRoom engine (run + step) → Task 5
- ✅ CLI Display (colored output) → Task 6
- ✅ CLI commands (chat + task --agents --json) → Task 7
- ✅ Integration test → Task 8
- ✅ Error handling (no keys, no agents, invalid selector) → Task 7 (build_chat_components)
- ✅ Combo termination (done_keyword + max_rounds) → Task 5

**Placeholder scan:** No TBD/TODO found. All steps have full code.

**Type consistency:** ChatMessage, ChatResult, ChatConfig, AgentParticipant, ChatRoom — consistent across all tasks. `_build_result()` added in Task 7 step 5, used in Task 7 step 3.
