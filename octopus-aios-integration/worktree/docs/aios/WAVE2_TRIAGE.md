# Wave 2 Triage: upstream-red tests

## Источник

Ветка AIOS `new` (tip 27.08): vNext runtime — WIP, тесты красные **на самом upstream**.
Проверено: чистый `git archive origin/new` + `pytest tests/ -o asyncio_mode=auto` →
те же падения, что и в порту (BYPASS: 3 теста исключены целиком — см. ниже).

## Карантин (21 тест, `@pytest.mark.skip WAVE2-QUARANTINE`)

| Тест | Симптом (upstream == port) |
|---|---|
| `agent_executor_protocol` ×2 | typed results / retry семантика не совпадает с кодом |
| `bootstrap_recovery_policy` ×1 | recovery policy не применяется при bootstrap |
| `execution_audit` ×1, `execution_audit_lifecycle` ×1 | append-only/persistence ожидания vs код |
| `execution_lease` ×1 | takeover просроченного lease |
| `execution_store` ×2 | `pending→completed` запрещён state-machine; `resumable()` пуст |
| `pr252_permission_boundary` ×1 | sandbox permissions обходятся |
| `recovery_checkpoint_integration` ×1 | loop не использует checkpoint |
| `recovery_manager` ×1 | resume pending executions |
| `reflection_bridge` ×2 | replan-триггеры |
| `runtime_orchestrator` ×1 | start→recover→execute |
| `security_hardening` ×2 | role/actor из headers; correlation-id |
| `shutdown_manager` ×2 | cancel/idempotency |
| `tool_protocol` ×2 | typed failure; timeout (0.001с не срабатывает) |
| `tool_registry` ×1 | plan+audit через executor |

## Исключены целиком (не портированы)

- `test_agent_executor.py`, `test_pr252_scheduler_tool_integration.py`, `test_execution_recovery_lifecycle.py` — импортируют `kernel.scheduler` / `agents.execution_manager` (вне замыкания Волны 2).
- `test_pr252_contracts.py` — in-function `from kernel.scheduler` + динамический `import api`.
- `test_api_main.py` — **адаптирован**, не исключён: upstream-тест целился в старое API `operator_validator → bool`; переписан на `authenticate()` + smoke `main.app`.

## План снятия с карантина

По мере реального использования модулей в Волнах 3–5: снять skip → воспроизвести →
решить (чинить код под тест или тест под код) → убрать маркер. Не снимать массово.

## Известный техдолг: CWD-relative `data/...` дефолты

6 модулей (`execution_store/lease/audit/commit`, `operator_audit`, `recovery_queue`)
по умолчанию пишут в относительный `data/...`. 4 теста пропатчены (`monkeypatch.chdir`),
но сами дефолты надо вынести в конфиг (`OCTOPUS_DATA_DIR`, по умолчанию
`/var/lib/octopus`) — при первом боевом использовании (Волны 3–5).
