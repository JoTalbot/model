# mDNS (LAN) + Chat Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional LAN mDNS advertisement and discovery for swarm nodes, and extend multi-agent chat with cost/reliability limits, optional rolling and final summaries, and optional LAN peer hints—without adding `zeroconf` to the base `requirements.txt`.

**Architecture:** Optional `requirements-mdns.txt` installs `zeroconf`; `swarm/network/mdns.py` wraps `zeroconf.asyncio.AsyncZeroconf` for register/browse and an in-memory peer cache. `node.py start` wires bootstrap-from-cache when YAML bootstrap is empty. Chat changes use a small `LLMCallBudget` type, message tail truncation, extended `ChatConfig`/`ChatResult`, and optional summary LLM calls inside `ChatRoom`/`AgentParticipant`.

**Tech Stack:** Python 3.11+, asyncio, `zeroconf` (optional), existing `click`, `pytest`, `pytest-asyncio`, `LLMRouter`, `KademliaNode`.

---

## File map (before tasks)

| Path | Responsibility |
|------|------------------|
| `requirements-mdns.txt` | Optional `zeroconf>=0.132.0` pin |
| `README.md` | Install note for mDNS extra; firewall note |
| `swarm/network/mdns.py` | `SwarmMDNS`: advertise + browse + peer cache |
| `swarm/chat/history.py` | Pure `truncate_messages_for_chars` helper |
| `swarm/chat/budget.py` | `LLMCallBudget` total + selector counters |
| `swarm/chat/room.py` | Extended config, budget, truncation, summaries, errors |
| `swarm/chat/participant.py` | `extra_system` prefix, truncation using `max_context_chars` |
| `swarm/chat/cli_display.py` | Print `end_reason` when present |
| `node.py` | Wire `SwarmMDNS`, bootstrap-from-mdns, browse-only for chat LAN hints |
| `config.yaml` | Add `mdns.*` and new `chat.*` keys (defaults only; no secrets) |
| `tests/test_history.py` | Truncation tests |
| `tests/test_budget.py` | Budget tests |
| `tests/test_chat_room.py` | Extend for new chat behaviors |
| `tests/test_mdns.py` | Mocked zeroconf tests |

---

### Task 1: Optional mDNS dependency + README + config defaults

**Files:**
- Create: `requirements-mdns.txt`
- Modify: `README.md`
- Modify: `config.yaml` (append new keys; preserve user-local values)

- [ ] **Step 1: Create `requirements-mdns.txt`**

```text
zeroconf>=0.132.0
```

- [ ] **Step 2: Append README section** (exact prose)

Add under a new heading `## Optional: LAN discovery (mDNS)`:

```markdown
Install multicast discovery (same code on Windows and Linux):

```bash
pip install -r requirements-mdns.txt
```

Enable in `config.yaml` with `mdns.enabled: true`. Open firewall for UDP 5353 (mDNS) and your node UDP/TCP ports (Kademlia, gossip, RPC).
```

- [ ] **Step 3: Merge into `config.yaml`** these blocks (if keys already exist, do not duplicate `llm.keys`):

```yaml
mdns:
  enabled: false
  service_type: "_immortal-swarm._tcp.local."
  initial_browse_seconds: 5
  refresh_interval_seconds: 60

chat:
  max_llm_calls_per_session: 30
  selector_max_llm_calls: 15
  max_context_chars: 12000
  retry_failed_round: false
  summary_every_n_agent_messages: 0
  summary_model: null
  final_summary: false
  lan_hints: false
```

Keep existing `chat:` keys (`max_rounds`, `selector`, `done_keyword`) and merge new keys into the same `chat:` mapping.

- [ ] **Step 4: Commit**

```bash
git add requirements-mdns.txt README.md config.yaml
git commit -m "chore: add optional mDNS deps and chat/mdns config defaults"
```

---

### Task 2: Message truncation helper

**Files:**
- Create: `swarm/chat/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write failing tests** in `tests/test_history.py`

```python
from swarm.chat.history import truncate_messages_for_chars
from swarm.chat.room import ChatMessage
import time


def _msg(name: str, content: str) -> ChatMessage:
    return ChatMessage(agent_name=name, role="r", content=content, round_num=1, timestamp=time.time())


def test_truncation_keeps_tail():
    msgs = [_msg("user", "A" * 100), _msg("parser", "B" * 100), _msg("analyst", "TAIL")]
    out = truncate_messages_for_chars(msgs, max_chars=150)
    assert len(out) == 1
    assert out[0].content == "TAIL"


def test_truncation_empty_safe():
    assert truncate_messages_for_chars([], 100) == []
```

- [ ] **Step 2: Run pytest (expect fail)**

Run: `pytest tests/test_history.py -v`  
Expected: import/hook failure until implementation exists.

- [ ] **Step 3: Implement** `swarm/chat/history.py`

```python
from __future__ import annotations

from swarm.chat.room import ChatMessage


def truncate_messages_for_chars(messages: list[ChatMessage], max_chars: int) -> list[ChatMessage]:
    if max_chars <= 0 or not messages:
        return list(messages)
    kept: list[ChatMessage] = []
    total = 0
    for m in reversed(messages):
        chunk = len(m.content) + 1
        if total + chunk > max_chars:
            break
        kept.append(m)
        total += chunk
    return list(reversed(kept))
```

- [ ] **Step 4: Run pytest (expect pass)**

Run: `pytest tests/test_history.py -v`

- [ ] **Step 5: Commit**

```bash
git add swarm/chat/history.py tests/test_history.py
git commit -m "feat: add chat message truncation helper"
```

---

### Task 3: LLM call budget

**Files:**
- Create: `swarm/chat/budget.py`
- Create: `tests/test_budget.py`

- [ ] **Step 1: Write failing tests** `tests/test_budget.py`

```python
import pytest
from swarm.chat.budget import LLMCallBudget, BudgetExceeded


def test_budget_blocks_total():
    b = LLMCallBudget(max_per_session=2, selector_max=5)
    b.consume_agent()
    b.consume_agent()
    with pytest.raises(BudgetExceeded):
        b.consume_agent()


def test_budget_blocks_selector():
    b = LLMCallBudget(max_per_session=10, selector_max=1)
    b.consume_selector()
    with pytest.raises(BudgetExceeded):
        b.consume_selector()


def test_summary_counts_as_agent():
    b = LLMCallBudget(max_per_session=1, selector_max=5)
    b.consume_summary()
    with pytest.raises(BudgetExceeded):
        b.consume_agent()
```

- [ ] **Step 2: Implement** `swarm/chat/budget.py`

```python
from __future__ import annotations


class BudgetExceeded(Exception):
    pass


class LLMCallBudget:
    def __init__(self, max_per_session: int, selector_max: int) -> None:
        self.max_per_session = max_per_session
        self.selector_max = selector_max
        self._total = 0
        self._selector = 0

    def consume_agent(self) -> None:
        self._consume_total(1)

    def consume_summary(self) -> None:
        self._consume_total(1)

    def consume_selector(self) -> None:
        if self._selector >= self.selector_max:
            raise BudgetExceeded("selector LLM budget exhausted")
        self._selector += 1
        self._consume_total(1)

    def _consume_total(self, n: int) -> None:
        if self._total + n > self.max_per_session:
            raise BudgetExceeded("session LLM budget exhausted")
        self._total += n
```

- [ ] **Step 3: Run pytest**

Run: `pytest tests/test_budget.py -v`

- [ ] **Step 4: Commit**

```bash
git add swarm/chat/budget.py tests/test_budget.py
git commit -m "feat: add LLM call budget for chat sessions"
```

---

### Task 4: Extend `ChatConfig` and `ChatResult`

**Files:**
- Modify: `swarm/chat/room.py`
- Modify: `tests/test_chat_room.py` (add small test for defaults)

- [ ] **Step 1: Extend dataclasses** in `swarm/chat/room.py`

Replace `ChatConfig` and `ChatResult` definitions with:

```python
@dataclass
class ChatResult:
    messages: list[ChatMessage]
    rounds_used: int
    finished_naturally: bool
    summary: str
    end_reason: str = ""
    epilogue: str = ""


@dataclass
class ChatConfig:
    max_rounds: int = 15
    done_keyword: str = "[DONE]"
    max_llm_calls_per_session: int = 30
    selector_max_llm_calls: int = 15
    max_context_chars: int = 12000
    retry_failed_round: bool = False
    summary_every_n_agent_messages: int = 0
    summary_model: str | None = None
    final_summary: bool = False
    lan_hints: bool = False
```

- [ ] **Step 2: Add test** in `tests/test_chat_room.py`

```python
def test_chat_config_extended_defaults():
    from swarm.chat.room import ChatConfig
    c = ChatConfig()
    assert c.selector_max_llm_calls == 15
    assert c.summary_every_n_agent_messages == 0
    assert c.final_summary is False
```

- [ ] **Step 3: Update all `ChatRoom(..., config=ChatConfig(...))` call sites in tests** to pass explicit `ChatConfig` if they relied on positional-only defaults (should still work).

- [ ] **Step 4: Run full pytest** `pytest -q`

- [ ] **Step 5: Commit**

```bash
git add swarm/chat/room.py tests/test_chat_room.py
git commit -m "feat: extend ChatConfig and ChatResult for chat controls"
```

---

### Task 5: `AgentParticipant.respond` — truncation + extra system text

**Files:**
- Modify: `swarm/chat/participant.py`
- Modify: `tests/test_chat_participant.py`

- [ ] **Step 1: Change signature** of `respond` to:

```python
async def respond(
    self,
    messages: list[ChatMessage],
    *,
    max_context_chars: int = 1_000_000,
    extra_system: str = "",
) -> str:
```

- [ ] **Step 2: Implementation sketch**

- Import `truncate_messages_for_chars` from `swarm.chat.history`.
- Build `truncated = truncate_messages_for_chars(messages, max_context_chars)`.
- `system_content = self.system_prompt` then if `extra_system`: append `\n\n` + `extra_system`.
- Build `prompt_messages` from `truncated` as today (first system, then per-message).

- [ ] **Step 3: Add test** `test_participant_truncates_and_extra_system`

```python
import time
import pytest
from unittest.mock import AsyncMock
from swarm.chat.participant import AgentParticipant
from swarm.chat.room import ChatMessage


@pytest.mark.asyncio
async def test_participant_truncates_and_extra_system():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="ok")
    p = AgentParticipant(name="p", role="r", system_prompt="SYS", llm=mock_llm)
    msgs = [ChatMessage("user", "u", "X" * 2000, 0, 0.0)]
    await p.respond(msgs, max_context_chars=100, extra_system="EXTRA")
    prompt = mock_llm.complete.call_args[0][0]
    assert "EXTRA" in prompt[0]["content"]
    total_chars = sum(len(m["content"]) for m in prompt if m["role"] != "system")
    assert total_chars <= 200
```

Adjust assertion to match actual prompt layout (system includes SYS+EXTRA).

- [ ] **Step 4: Update `ChatRoom.step`** temporarily still calls `respond(self.messages)` — fix in Task 6 to pass kwargs.

- [ ] **Step 5: Commit**

```bash
git add swarm/chat/participant.py tests/test_chat_participant.py
git commit -m "feat: truncate chat history and allow extra system context"
```

---

### Task 6: `ChatRoom` — budget, errors, truncation wiring, end_reason

**Files:**
- Modify: `swarm/chat/room.py`
- Modify: `tests/test_chat_room.py`

- [ ] **Step 1: Constructor** `ChatRoom.__init__` gains optional `budget: LLMCallBudget | None = None`. If `None`, construct `LLMCallBudget(config.max_llm_calls_per_session, config.selector_max_llm_calls)`.

- [ ] **Step 2: In `step`**

1. If `_finished` or rounds cap: return `None` (unchanged).
2. Before selector: `try: self._budget.consume_selector()` except `BudgetExceeded`: set `_finished=True`, `_end_reason="LLM call budget exhausted"` (new private field), return `None`.
3. After `chosen_name`, before respond: `try: self._budget.consume_agent()` except `BudgetExceeded`: same as above.
4. Call `await participant.respond(self.messages, max_context_chars=self.config.max_context_chars, extra_system=self._compose_extra_system())` where `_compose_extra_system` returns `""` in this task (LAN + rolling added in Task 7–8).
5. Wrap `respond` in try/except: on exception, append `ChatMessage` with content `"[ERROR] " + short str(exc)` without incrementing successful LLM (do **not** consume budget twice; spec: optional retry off — do not retry).

- [ ] **Step 3: `_build_result`** sets `end_reason=self._end_reason` on `ChatResult`.

- [ ] **Step 4: Tests** with mocks: force `BudgetExceeded` by tiny limits; assert `end_reason` non-empty.

- [ ] **Step 5: Commit**

```bash
git add swarm/chat/room.py tests/test_chat_room.py
git commit -m "feat: wire LLM budget and error handling into ChatRoom"
```

---

### Task 7: Rolling summary + final summary

**Files:**
- Modify: `swarm/chat/room.py`
- Modify: `tests/test_chat_room.py`

- [ ] **Step 1: ChatRoom fields** `rolling_summary: str = ""`, `_agent_messages_since_summary: int = 0`, optional `summary_llm: object | None` passed from `node.py` (same `LLMRouter` instance built from `summary_model` or first `llm.models`).

- [ ] **Step 2: After appending agent message** in `step`, if `config.summary_every_n_agent_messages > 0` and counter hits N: call `await self._run_rolling_summary()` which uses `summary_llm.complete` with bullet prompt over last messages; `self._budget.consume_summary()` before call.

- [ ] **Step 3: `_compose_extra_system`** returns `self.rolling_summary` prefixed with `Rolling context:\n` when non-empty.

- [ ] **Step 4: In `run` after loop** if `config.final_summary` and budget allows: `consume_summary`, one LLM call, append to `ChatResult.summary` or separate field — spec says print under Итог: extend `ChatResult` with `final_summary_text: str = ""` OR overload `summary` — prefer new field `epilogue: str = ""` to avoid breaking JSON consumers; update `ChatDisplay.show_result` to print `epilogue` when set.

Use `epilogue` on `ChatResult`.

- [ ] **Step 5: Tests** with mocked `summary_llm` verifying rolling triggers every N.

- [ ] **Step 6: Commit**

```bash
git add swarm/chat/room.py swarm/chat/cli_display.py tests/test_chat_room.py tests/test_chat_display.py
git commit -m "feat: add rolling and final chat summaries"
```

---

### Task 8: LAN hint block plumbing

**Files:**
- Modify: `swarm/chat/room.py`
- Modify: `node.py`

- [ ] **Step 1: ChatRoom.__init__** accepts optional `lan_peers_lines: list[str] | None`. On first `step` after `start`, if lines non-empty, inject once into `_lan_block` string (max 10 lines) used inside `_compose_extra_system`.

- [ ] **Step 2: Unit test** ensures LAN block appears only on first agent call (track mock LLM first prompt).

- [ ] **Step 3: Commit**

```bash
git add swarm/chat/room.py tests/test_chat_room.py
git commit -m "feat: inject optional LAN peer hints into first agent turn"
```

---

### Task 9: `SwarmMDNS` module (mocked tests)

**Files:**
- Create: `swarm/network/mdns.py`
- Create: `tests/test_mdns.py`

- [ ] **Step 1: API**

```python
class SwarmMDNS:
    def __init__(self, service_type: str, refresh_interval: float, initial_browse: float) -> None: ...
    async def start(self, *, host: str, ports: dict[str, int], node_id: str, instance_suffix: str) -> None: ...
    async def stop(self) -> None: ...
    def peers_snapshot(self) -> list[dict]: ...
```

`peers_snapshot` returns dicts like `{"host": "...", "kad": 8000, "kid": "...", "last_seen": float}`.

- [ ] **Step 2: Implementation** uses `from zeroconf import ServiceInfo` and `from zeroconf.asyncio import AsyncZeroconf, AsyncServiceListener` (adjust imports to match installed `zeroconf` 0.132 API—verify in venv after `pip install -r requirements-mdns.txt`).

- [ ] **Step 3: Tests** patch `zeroconf.asyncio.AsyncZeroconf` with `AsyncMock`; assert `start`/`stop` called and cache updated when listener fires fake `ServiceStateChange.Added`.

- [ ] **Step 4: Commit**

```bash
git add swarm/network/mdns.py tests/test_mdns.py
git commit -m "feat: add optional SwarmMDNS LAN discovery wrapper"
```

---

### Task 10: `node.py` integration — start + chat/task

**Files:**
- Modify: `node.py`

- [ ] **Step 1: Helper `def _mdns_available() -> bool`**

```python
def _mdns_available() -> bool:
    try:
        import zeroconf  # noqa: F401
    except ImportError:
        return False
    return True
```

- [ ] **Step 2: `start_node`**

After `kad.start(...)` succeeds and `cfg.get("mdns", {}).get("enabled")`:

- If not `_mdns_available()`: log once at INFO that mDNS is disabled (missing package).
- Else instantiate `SwarmMDNS`, `await mdns.start(...)` with ports from `port`, register, start browse task loop until shutdown; on bootstrap: if YAML `node.bootstrap` empty, iterate `peers_snapshot()` ordered by `last_seen` descending and attempt `await kad._server.bootstrap([(h, kad_port)])` or re-call existing `start` pattern—**implementation detail:** because `KademliaNode.start` already ran, add package-level helper on `KademliaNode` **or** call internal `await kad._server.bootstrap([...])` only if public API missing (prefer add `async def bootstrap_more(self, addrs)` to `kademlia.py` in this task to avoid private access).

Minimal change: extend `KademliaNode` with:

```python
async def bootstrap_peers(self, addrs: list[tuple[str, int]]) -> None:
    if addrs:
        await self._server.bootstrap(addrs)
```

Call after mDNS initial browse window.

- [ ] **Step 3: `run_chat_interactive` / `run_task_oneshot`**

If `chat.lan_hints` and mdns enabled and `_mdns_available()`: create short-lived `SwarmMDNS` browse-only (constructor flag `register=False` or separate class `SwarmMDNSBrowseOnly`) — simplest: reuse `SwarmMDNS` with `start(register=False)` parameter default `True`.

Pass `peers_snapshot()` formatted lines into `ChatRoom(..., lan_peers_lines=...)`.

- [ ] **Step 4: Wire `summary_llm` and extended `ChatConfig` from YAML** inside `build_chat_components`: map new keys into `ChatConfig(...)`.

- [ ] **Step 5: Run full pytest**

- [ ] **Step 6: Commit**

```bash
git add node.py swarm/network/kademlia.py
git commit -m "feat: integrate mDNS and LAN hints into node and chat CLI"
```

---

## Plan self-review

- **Spec coverage:** mDNS optional dep, advertise/browse, bootstrap from cache, chat limits, summaries, LAN hints, `ChatDisplay` updates — all mapped to tasks.
- **Placeholder scan:** none intentional; Task 9 notes verify zeroconf imports against venv (concrete, not TBD behavior).
- **Consistency:** `ChatResult.epilogue` introduced in Task 7 must match `cli_display` and any JSON `task --json` serialization in `node.py` (update JSON dump to include `epilogue` and `end_reason` when present).

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-05-13-mdns-and-chat.md`.

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks.

**2. Inline Execution** — same session with executing-plans checkpoints.

Which approach do you want?
