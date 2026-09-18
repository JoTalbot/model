# Memory ontology + MemoryPort facade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an **additive** memory facade (`MemoryPort`) with `ref:<scheme>:<opaque>` routing, pluggable adapters (local scratch + DHT/RS swarm + HTTP link read), **`promote`** from scratch to swarm, optional **`attrs`** on `MemoryBlock` for ontology metadata, and YAML-driven composition—without removing `DistributedMemory` as the network engine.

**Architecture:** Small focused modules under `swarm/memory/`: value types and ref parsing, adapter protocol, three MVP adapters, a **composite** facade with a scheme registry and per-adapter `Capabilities`. `DistributedMemory` gains backward-compatible **optional `attrs`** in msgpack meta. Local adapter stores blobs + sidecar JSON metadata under a configured directory.

**Tech Stack:** Python 3.11+, asyncio, dataclasses, `msgpack`, `httpx` (already in project), `pytest` + `pytest-asyncio`, existing `DistributedMemory` / `ErasureCoder` / Kademlia wiring from tests.

**Note:** Brainstorming mentioned a dedicated git worktree; if your workflow uses one, check out this plan there. Otherwise implement on your normal branch.

---

## File map (target layout)

| Path | Responsibility |
|------|------------------|
| `swarm/memory/types.py` | `Artifact`, `RefMeta`, `Capabilities`, facade exceptions |
| `swarm/memory/ref_parse.py` | `parse_ref`, `make_ref` — validate `ref:<scheme>:<opaque>` |
| `swarm/memory/port.py` | `MemoryPort` typing.Protocol + `MemoryAdapter` Protocol + `MemoryMetrics` |
| `swarm/memory/adapters/local_scratch.py` | `LocalScratchAdapter` (`scheme` `file`) |
| `swarm/memory/adapters/swarm_store.py` | `DhtErasureAdapter` (`scheme` `swarm`) wrapping `DistributedMemory` |
| `swarm/memory/adapters/http_link.py` | `LinkAdapter` (`scheme` `http` / `https`) |
| `swarm/memory/composite.py` | `CompositeMemoryPort` — registry, dispatch, `promote`, aggregated `capabilities` |
| `swarm/memory/factory.py` | `build_memory_port(cfg, distributed_memory)` reading YAML |
| `swarm/memory/store.py` | Extend `MemoryBlock`, meta msgpack for optional `attrs` |
| `config.yaml` | New optional `memory_facade:` block (defaults off / minimal) |
| `tests/test_ref_parse.py` | Ref parsing |
| `tests/test_memory_store.py` | Meta round-trip `attrs` (with other store tests) |
| `tests/test_adapter_local_scratch.py` | Local adapter |
| `tests/test_adapter_swarm_store.py` | Swarm adapter with mocked `DistributedMemory` |
| `tests/test_adapter_http_link.py` | Link adapter with `httpx.MockTransport` |
| `tests/test_composite_memory_port.py` | Facade routing + `promote` |
| `tests/test_memory_factory.py` | YAML → facade smoke |
| `README.md` | Short subsection documenting optional facade and config keys |

---

### Task 1: Ref parsing utilities

**Files:**
- Create: `swarm/memory/ref_parse.py`
- Create: `tests/test_ref_parse.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_ref_parse.py
import pytest
from swarm.memory.ref_parse import make_ref, parse_ref


def test_parse_round_trip():
    r = make_ref("swarm", "abc-123")
    assert r == "ref:swarm:abc-123"
    scheme, opaque = parse_ref(r)
    assert scheme == "swarm"
    assert opaque == "abc-123"


def test_parse_https_opaque_may_contain_colons():
    opaque = "example.com%2Fpath"  # caller may URL-encode; parser must not split extra colons
    r = make_ref("https", opaque)
    scheme, out = parse_ref(r)
    assert scheme == "https"
    assert out == opaque


def test_parse_rejects_bad_prefix():
    from swarm.memory.ref_parse import RefFormatError

    with pytest.raises(RefFormatError):
        parse_ref("swarm:abc")
```

- [x] **Step 2: Run tests — expect import / collection failure**

Run: `pytest tests/test_ref_parse.py -v`  
Expected: fails (module missing).

- [x] **Step 3: Implement `swarm/memory/ref_parse.py`**

```python
# swarm/memory/ref_parse.py
from __future__ import annotations

PREFIX = "ref:"


class RefFormatError(ValueError):
    pass


def make_ref(scheme: str, opaque: str) -> str:
    if not scheme or ":" in scheme:
        raise RefFormatError("invalid scheme")
    if opaque is None or opaque == "":
        raise RefFormatError("opaque must be non-empty")
    return f"{PREFIX}{scheme}:{opaque}"


def parse_ref(ref: str) -> tuple[str, str]:
    if not ref.startswith(PREFIX):
        raise RefFormatError("ref must start with ref:")
    rest = ref[len(PREFIX) :]
    idx = rest.find(":")
    if idx <= 0 or idx == len(rest) - 1:
        raise RefFormatError("ref must be ref:<scheme>:<opaque>")
    scheme, opaque = rest[:idx], rest[idx + 1 :]
    if not scheme:
        raise RefFormatError("empty scheme")
    return scheme, opaque
```

- [x] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_ref_parse.py -v`

- [x] **Step 5: Commit**

```bash
git add swarm/memory/ref_parse.py tests/test_ref_parse.py
git commit -m "feat: add ref: scheme:opaque parsing for memory facade"
```

---

### Task 2: Value types + exceptions

**Files:**
- Create: `swarm/memory/types.py`
- Create: `tests/test_memory_types.py`

- [x] **Step 1: Write failing tests**

```python
# tests/test_memory_types.py
from swarm.memory.types import Artifact, Capabilities, RefMeta


def test_artifact_defaults():
    a = Artifact(content=b"hi")
    assert a.content == b"hi"
    assert a.mime == "application/octet-stream"
    assert a.tags == []
    assert a.provenance == {}
    assert a.attrs == {}


def test_capabilities_frozen_schemes():
    c = Capabilities(schemes=frozenset({"file", "swarm"}), supports_search=True, supports_delete=True, supports_promote=True)
    assert "file" in c.schemes


def test_ref_meta():
    m = RefMeta(ref="ref:file:x", scheme="file", tags=["a"], block_type="knowledge")
    assert m.ref.startswith("ref:")
```

- [x] **Step 2: Run pytest (expect fail)**

Run: `pytest tests/test_memory_types.py -v`

- [x] **Step 3: Implement `swarm/memory/types.py`**

```python
# swarm/memory/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    content: bytes | str
    mime: str = "application/octet-stream"
    tags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefMeta:
    ref: str
    scheme: str
    tags: list[str] = field(default_factory=list)
    block_type: str | None = None


@dataclass(frozen=True)
class Capabilities:
    schemes: frozenset[str]
    supports_search: bool
    supports_delete: bool
    supports_promote: bool


class RefNotFoundError(LookupError):
    pass


class MemoryAdapterError(RuntimeError):
    pass


class WormConflictError(MemoryAdapterError):
    pass


class PromotionError(MemoryAdapterError):
    pass
```

- [x] **Step 4: Run pytest — PASS**

Run: `pytest tests/test_memory_types.py -v`

- [x] **Step 5: Commit**

```bash
git add swarm/memory/types.py tests/test_memory_types.py
git commit -m "feat: add Artifact RefMeta Capabilities and memory facade errors"
```

---

### Task 3: Optional `attrs` on `MemoryBlock` + DHT meta

**Files:**
- Modify: `swarm/memory/store.py`
- Modify: `tests/test_memory_store.py`

- [x] **Step 1: Add failing test for attrs round-trip**

Append to `tests/test_memory_store.py`:

```python
import pytest
from unittest.mock import AsyncMock
import msgpack
from swarm.memory.store import DistributedMemory, MemoryBlock
from swarm.memory.erasure import ErasureCoder


@pytest.mark.asyncio
async def test_store_retrieve_round_trip_with_attrs():
    k = AsyncMock()
    storage = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    coder = ErasureCoder(data_shards=4, parity_shards=2)
    mem = DistributedMemory(k, AsyncMock(), coder, node_id="n1")

    attrs = {"schema_version": 1, "dur": "scratch"}
    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"payload",
        tags=["t1"],
        attrs=attrs,
    )
    bid = await mem.store(block)
    out = await mem.retrieve(bid)
    assert out is not None
    assert out.attrs == attrs
    meta = msgpack.unpackb(storage[f"meta:{bid}"], raw=False)
    assert meta.get("attrs") == attrs
```

- [x] **Step 2: Run test — expect FAIL** (no `attrs` on dataclass / meta)

Run: `pytest tests/test_memory_store.py::test_store_retrieve_round_trip_with_attrs -v`

- [x] **Step 3: Implement**

In `MemoryBlock` add:

```python
    attrs: dict | None = None
```

In `store()` meta dict add after tags:

```python
            "attrs": block.attrs or {},
```

In `retrieve()` when building `MemoryBlock`, pass `attrs=meta.get("attrs") or None` (use `{}` as empty dict vs None — pick **empty dict** for consistency: `attrs=meta.get("attrs") or {}` only if spec wants always dict; spec says optional — use `meta.get("attrs")` and if missing pass `None`).

Recommended: **`attrs=None` in Python if key missing or empty dict stored as `{}`** — store always serializes `attrs` key; unpack uses `meta.get("attrs")` → if absent, `MemoryBlock(attrs=None)`.

- [x] **Step 4: Run full memory store tests**

Run: `pytest tests/test_memory_store.py -v`

- [x] **Step 5: Commit**

```bash
git add swarm/memory/store.py tests/test_memory_store.py
git commit -m "feat: optional attrs on MemoryBlock and DHT metadata"
```

---

### Task 4: Adapter protocol + metrics

**Files:**
- Create: `swarm/memory/port.py`
- Create: `swarm/memory/adapters/__init__.py`
- Create: `tests/test_memory_metrics.py`

- [x] **Step 1: Test metrics increments**

```python
# tests/test_memory_metrics.py
from swarm.memory.port import MemoryMetrics


def test_metrics_increment():
    m = MemoryMetrics()
    m.record_put("file")
    m.record_get("file", ok=True)
    m.record_get("swarm", ok=False)
    assert m.puts["file"] == 1
    assert m.gets_ok["file"] == 1
    assert m.gets_err["swarm"] == 1
```

- [x] **Step 2: Implement `swarm/memory/port.py`**

```python
# swarm/memory/port.py
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from swarm.memory.types import Artifact, Capabilities, RefMeta

if TYPE_CHECKING:
    pass


class MemoryMetrics:
    def __init__(self) -> None:
        self.puts: dict[str, int] = {}
        self.gets_ok: dict[str, int] = {}
        self.gets_err: dict[str, int] = {}

    def record_put(self, scheme: str) -> None:
        self.puts[scheme] = self.puts.get(scheme, 0) + 1

    def record_get(self, scheme: str, *, ok: bool) -> None:
        d = self.gets_ok if ok else self.gets_err
        key = scheme
        d[key] = d.get(key, 0) + 1


@runtime_checkable
class MemoryAdapter(Protocol):
    scheme: str

    async def put(self, artifact: Artifact) -> str: ...
    async def get(self, ref: str) -> Artifact: ...
    async def exists(self, ref: str) -> bool: ...
    async def delete(self, ref: str) -> bool: ...
    async def search(self, tags: list[str], owner: str | None) -> list[RefMeta]: ...
    def capabilities(self) -> Capabilities: ...


@runtime_checkable
class MemoryPort(Protocol):
    async def put(self, artifact: Artifact) -> str: ...
    async def get(self, ref: str) -> Artifact: ...
    async def exists(self, ref: str) -> bool: ...
    async def delete(self, ref: str) -> bool: ...
    async def search(self, tags: list[str], owner: str | None = None) -> list[RefMeta]: ...
    async def promote(self, ref: str) -> str: ...
    def capabilities(self) -> Capabilities: ...
    @property
    def metrics(self) -> MemoryMetrics: ...
```

- [x] **Step 3: Run** `pytest tests/test_memory_metrics.py -v`

- [x] **Step 4: Commit**

```bash
git add swarm/memory/port.py swarm/memory/adapters/__init__.py tests/test_memory_metrics.py
git commit -m "feat: add MemoryPort MemoryAdapter protocols and metrics"
```

---

### Task 5: `LocalScratchAdapter`

**Files:**
- Create: `swarm/memory/adapters/local_scratch.py`
- Create: `tests/test_adapter_local_scratch.py`

**Behavior:** `put` writes `scratch_root/<opaque>/blob` and `scratch_root/<opaque>/meta.json` (JSON: mime, tags, provenance, attrs). `opaque` is a new UUID string; returned ref is `make_ref("file", opaque)`. WORM / `dur:worm` enforcement is **deferred** (follow-up); this task only put/get/exists/delete.

- [x] **Step 1: Failing tests**

```python
# tests/test_adapter_local_scratch.py
import pytest

from swarm.memory.types import Artifact
from swarm.memory.ref_parse import parse_ref
from swarm.memory.adapters.local_scratch import LocalScratchAdapter


@pytest.mark.asyncio
async def test_local_put_get(tmp_path):
    a = LocalScratchAdapter(root=tmp_path)
    art = Artifact(content=b"hello", mime="text/plain", tags=["note"])
    ref = await a.put(art)
    scheme, _ = parse_ref(ref)
    assert scheme == "file"
    out = await a.get(ref)
    assert out.content == b"hello"
    assert "note" in out.tags


@pytest.mark.asyncio
async def test_local_delete(tmp_path):
    a = LocalScratchAdapter(root=tmp_path)
    ref = await a.put(Artifact(content=b"x"))
    assert await a.exists(ref) is True
    assert await a.delete(ref) is True
    assert await a.exists(ref) is False
```

- [x] **Step 2: Implement `LocalScratchAdapter`** (uuid dirs, meta.json, `make_ref("file", uuid)`)

- [x] **Step 3: pytest** `tests/test_adapter_local_scratch.py -v`

- [x] **Step 4: Commit** `feat: add LocalScratchAdapter for memory facade`

---

### Task 6: `DhtErasureAdapter`

**Files:**
- Create: `swarm/memory/adapters/swarm_store.py`
- Create: `tests/test_adapter_swarm_store.py`

- [x] **Step 1: Tests with mocked `DistributedMemory`**

```python
# tests/test_adapter_swarm_store.py
from unittest.mock import AsyncMock, MagicMock
import pytest

from swarm.memory.types import Artifact
from swarm.memory.adapters.swarm_store import DhtErasureAdapter


@pytest.mark.asyncio
async def test_swarm_put_get_uses_distributed_memory():
    dm = MagicMock()
    dm.store = AsyncMock(return_value="block-uuid-1")
    dm.retrieve = AsyncMock(return_value=None)

    ad = DhtErasureAdapter(dm, default_block_type="knowledge", owner_id="node-a")
    ref = await ad.put(Artifact(content=b"data", tags=["x"], provenance={"source": "t"}))
    assert ref == "ref:swarm:block-uuid-1"
    dm.store.assert_awaited()
    call_kw = dm.store.await_args[0][0]
    # first positional arg is MemoryBlock in real code — assert isinstance MemoryBlock and content
    from swarm.memory.store import MemoryBlock

    assert isinstance(call_kw, MemoryBlock)
    assert call_kw.content == b"data"
```

- [x] **Step 2: Implement** mapping `Artifact` → `MemoryBlock(owner_id=..., block_type=artifact.attrs.get("block_type") or default, ...)`

- [x] **Step 3: `get`** parses ref, calls `retrieve(opaque)`, maps back to `Artifact`.

- [x] **Step 4: Commit**

---

### Task 7: `LinkAdapter` (read-mostly)

**Files:**
- Create: `swarm/memory/adapters/http_link.py`
- Create: `tests/test_adapter_http_link.py`

- [x] **Step 1: Test with `httpx.MockTransport`**

```python
import httpx
import pytest
from swarm.memory.adapters.http_link import LinkAdapter


@pytest.mark.asyncio
async def test_link_get():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"OK"))
    async with httpx.AsyncClient(transport=transport) as client:
        ad = LinkAdapter(client)
        art = await ad.get("ref:https:example.com%2F")
        assert art.content == b"OK"
```

- [x] **Step 2: Implement** — `put` raises `MemoryAdapterError` (read-only); `exists` HEAD request optional or always True for well-formed URL; **YAGNI:** `exists` returns True if URL parses.

- [x] **Step 3: Commit**

---

### Task 8: `CompositeMemoryPort` + `promote`

**Files:**
- Create: `swarm/memory/composite.py`
- Create: `tests/test_composite_memory_port.py`

**Behavior:**

- Registry: `dict[str, MemoryAdapter]` for schemes `file`, `swarm`, `http`, `https`.
- `put`: inspect `artifact.attrs.get("target_scheme")` or **default route**: if `attrs["route"] == "swarm"` use swarm else file. **Simpler v1:** always `file` unless `artifact.attrs.get("store") == "swarm"` then swarm.
- `get`/`delete`/`exists`: `parse_ref` → dispatch.
- `search`: `asyncio.gather` from adapters where `capabilities().supports_search`, dedupe refs.
- `promote(ref)`: if `file` → read artifact → `put` to swarm adapter → return new ref; on failure raise `PromotionError`.

- [x] **Step 1: Integration-style test**

```python
@pytest.mark.asyncio
async def test_promote_file_to_swarm(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from swarm.memory.types import Artifact
    from swarm.memory.composite import CompositeMemoryPort
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.adapters.swarm_store import DhtErasureAdapter

    dm = MagicMock()
    dm.store = AsyncMock(return_value="swarmed-id")

    local = LocalScratchAdapter(tmp_path)
    swarm = DhtErasureAdapter(dm, default_block_type="knowledge", owner_id="n")
    comp = CompositeMemoryPort({"file": local, "swarm": swarm})
    ref = await comp.put(Artifact(content=b"z"))
    new_ref = await comp.promote(ref)
    assert new_ref.startswith("ref:swarm:")
```

- [x] **Step 2: Implement `CompositeMemoryPort`**

- [x] **Step 3: Commit** `feat: add CompositeMemoryPort with promote file to swarm`

---

### Task 9: YAML factory + docs

**Files:**
- Create: `swarm/memory/factory.py`
- Create: `tests/test_memory_factory.py`
- Modify: `config.yaml` (optional keys under `memory_facade:`)
- Modify: `README.md`

Example `config.yaml` fragment:

```yaml
memory_facade:
  enabled: false
  scratch_root: ".swarm_scratch"
  default_put_route: "file"   # or "swarm"
```

`build_memory_port(cfg, distributed_memory)` returns `CompositeMemoryPort | None` if `enabled` false.

- [x] **Step 1: Test factory returns None when disabled**

```python
def test_factory_disabled():
    from swarm.memory.factory import build_memory_port

    assert build_memory_port({"memory_facade": {"enabled": False}}, None) is None
```

- [x] **Step 2: Implement factory**

- [x] **Step 3: README** — 6–10 lines: what the facade is, `memory_facade.enabled`, install path unchanged.

- [x] **Step 4: Commit** `feat: add memory facade YAML factory and README`

---

### Task 10: WORM на `LocalScratchAdapter`

**Goal:** Для артефактов с тегом `dur:worm` запретить «тихую» перезапись уже существующего ref: повторная запись того же логического объекта должна завершаться `WormConflictError`.

**Files:**
- Modify: `swarm/memory/adapters/local_scratch.py`
- Modify: `tests/test_adapter_local_scratch.py`

**Behavior (v2):**

- После первого успешного `put` возвращается `ref:file:<opaque>`.
- Если во втором вызове `put` у `Artifact` есть тег `dur:worm` **и** в `artifact.attrs` передан ключ `"worm_base_ref"` (строка ref, ранее возвращённый `put`), то адаптер **парсит** этот ref, убеждается что он указывает на тот же `scratch_root`, и если каталог существует и новое тело **отличается** от сохранённого `blob` — бросает `WormConflictError` из `swarm.memory.types`.
- Если тело идентично байт-в-байт — можно вернуть тот же ref (идемпотентность) **или** бросать конфликт всегда (выберите одно поведение в реализации и зафиксируйте в тесте одной строкой в docstring адаптера).

- [x] **Step 1: Написать тест** `test_worm_second_put_conflict` — первый `put` с `dur:worm`, второй с тем же `worm_base_ref` и другим `content` → `pytest.raises(WormConflictError)`.

- [x] **Step 2: Реализовать** проверку в `LocalScratchAdapter.put` до записи на диск.

- [x] **Step 3:** `pytest tests/test_adapter_local_scratch.py -v` и `pytest -q`.

- [x] **Step 4: Commit** `feat: enforce WORM semantics on local scratch adapter`

---

### Task 11: Подключить фасад в `SwarmAgent` и `skills.py`

**Goal:** Опционально собирать `CompositeMemoryPort` через `build_memory_port` и использовать его в агентском коде вместо прямого вызова только `DistributedMemory`, когда `memory_facade.enabled: true`.

**Files:**
- Modify: `swarm/agent/core.py` — поле `memory_port` (опционально), инициализация из конфига + переданный `DistributedMemory`.
- Modify: `swarm/agent/skills.py` — пути записи блоков (например результаты парсера) через `memory_port.put` с маршрутизацией `attrs["store"]` по смыслу задачи; fallback на существующий `memory.store` если порт `None`.
- Modify: `node.py` — после создания `DistributedMemory` и загрузки `cfg` вызвать `build_memory_port(cfg, memory)` и передать в `SwarmAgent`.
- Modify или create: `tests/...` — один тест регрессии с `memory_facade.enabled: false` и один с `enabled: true` + mock `DistributedMemory` (проверка что `put` уходит в фасад).

**Non-goals (этой задачи):** смена формата RPC между узлами; обязательный фасад для всех нод.

- [x] **Step 1: Тест «без фасада»** — текущее поведение без изменений конфига.

- [x] **Step 2: Тест с `enabled: true`** — mock, assert что `skills`/`core` вызывают `memory_port.put` (или обёртку).

- [x] **Step 3: Реализация** проводки параметров `cfg` → `SwarmAgent` → `skills`.

- [x] **Step 4:** `pytest -q`.

- [x] **Step 5: Commit** `feat: wire memory facade into SwarmAgent and skills`

---

### Task 12: Фоновый repair недостающих шардов (DistributedMemory)

**Goal:** Периодически пытаться восстановить полноту шардов для блоков, известных по `meta:*`, если обнаружены дырки (меньше `data_shards` уникальных шардов), — без блокировки основного цикла агента.

**Files:**
- Modify: `swarm/memory/store.py` — метод `async def repair_shards_once(self, block_id: str) -> bool` и/или `async def scan_and_repair_round(self) -> int` (число затронутых блоков за проход).
- Modify: `swarm/agent/core.py` (или новый `swarm/memory/repair_loop.py`) — фоновая задача с интервалом из `config.yaml`: ключ `memory.repair_interval_seconds`, default **`0`** = цикл выключен.
- Modify: `config.yaml` — `memory.repair_interval_seconds: 0` по умолчанию.
- Modify или create: `tests/test_memory_repair.py` — mock `get` для шардов: сначала неполный набор, после логики repair — полный; assert `retrieve` успешен.

**Ограничения v1:** если API вытягивания шардов с удалённой ноды ещё нет, внутри `repair_shards_once` допускается **явная заглушка**: лог `INFO`, возврат `False`, без слова `TBD` в коде — плюс комментарий «заменить при появлении RPC pull шардов».

- [x] **Step 1: Юнит-тест** на `repair_shards_once` / `scan_and_repair_round` с mock Kademlia.

- [x] **Step 2: Реализация** сбора шардов и повторного чтения после дозаполнения из DHT (локальная нода).

- [x] **Step 3: Фоновый цикл** за конфигом, отмена при остановке агента.

- [x] **Step 4:** `pytest -q`.

- [x] **Step 5: Commit** `feat: add background shard repair for distributed memory`

---

## Plan self-review

**1. Spec coverage**

| Spec section | Task(s) |
|--------------|---------|
| Part P1 ref surface | Task 1 |
| Part P1 Artifact | Task 2 |
| Part P2 registry / capabilities | Tasks 4, 8 (`capabilities` aggregation on composite: union of schemes; `supports_search` OR of adapters) |
| Part P3 metrics | Task 4 |
| Part P4 local-first | Tasks 5, 8 (file default route), factory default `file` |
| Part P5 durability / promote | Task 3 `attrs`, Task 8 `promote`, **Task 10** WORM на scratch |
| Part B ontology (axes in attrs) | Task 3 attrs + adapters preserve attrs |
| Part C MVP adapters | Tasks 5–7 |
| Testing table | Tasks 1–12 доставлены в репозитории |
| Интеграция агента | **Task 11** |
| Устойчивость к потере шардов | **Task 12** |

**Follow-up (после Tasks 10–12):** полная таблица маршрутизации по тегам/типам без `attrs["store"]`; шифрование содержимого DHT; вынос repair в отдельный процесс.

**2. Placeholder scan:** В Tasks 10–12 нет строки `TBD`; для Task 12 задано явное поведение заглушки, если RPC pull шардов отсутствует.

**3. Type consistency:** Имена `worm_base_ref` и `memory.repair_interval_seconds` вводятся здесь — использовать их же в коде и YAML при реализации Tasks 10–12.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-13-memory-ontology-and-facade.md`.

**Phase 1 (Tasks 1–9)** — доставлено в репозитории (см. история коммитов).

**Phase 2 (Tasks 10–12)** — доставлено в репозитории (WORM на scratch, проводка фасада в агент/`skills`, repair-заглушка + фоновый цикл по `memory.repair_interval_seconds`). Повторная проверка: `pytest -q` и блок **Verification (rerun)** в спеке `docs/superpowers/specs/2026-05-13-memory-ontology-and-facade-design.md`.
