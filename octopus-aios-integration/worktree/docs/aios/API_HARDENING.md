# API Hardening (Волна 2, пункт 12)

## Что сделано

1. **`swarm/api/hardening.py`** (новый, stdlib-only) — RBAC + fail-closed auth + CORS-allowlist:
   - роли `viewer < operator < admin`, токен→роль мапа (мин. 16 символов);
   - `require_auth: true` — fail-closed (без кредов → 401/403);
   - `localhost_bypass` (по умолчанию true) — 127.0.0.1 без кредов = operator;
   - делегирование HTTP Basic в legacy `DashboardAuth`;
   - аудит-кольцо отклонённых попыток (`audit_stats()`).
2. **`swarm/api/control_plane.py`** (патч, поведение по умолчанию НЕ изменено):
   - `_check_auth(minimum_role)` — POST требует `operator` (только когда включён hardened);
   - CORS `*` → allowlist из конфига (`dashboard.cors_origins`, по умолчанию `["*"]`);
   - `ControlPlaneServer(..., hardened=..., cors_origins=...)`;
   - громкий WARNING в лог, если сервер на не-localhost без auth.
3. **`swarm/tools_runtime/api_kit/`** — FastAPI-референс из AIOS (`security`, `auth_config`, `recovery_rbac`, `operator_audit`, `app`, `main`) как есть, для будущих FastAPI-сервисов.
4. **Тесты**: `tests/test_api_hardening.py` (16 тестов, вкл. live-HTTP интеграцию) + 41 портированный тест `tools_runtime`/`api_kit`.

## Как включить (отдельная команда, НЕ включено по умолчанию)

```yaml
# config.yaml
dashboard:
  require_auth: true
  localhost_bypass: false        # строгий режим (иначе true)
  tokens:
    "op-секрет-мин-16-символов": operator
    "ro-секрет-мин-16-символов": viewer
  cors_origins:
    - "https://dash.example.com"
```

```python
from swarm.api.auth import DashboardAuth
from swarm.api.hardening import build_hardened_auth
hardened = build_hardened_auth(cfg, legacy=DashboardAuth(cfg))
server = ControlPlaneServer(metrics, hardened=hardened,
                            cors_origins=cfg["dashboard"].get("cors_origins"))
```

## Проверка

```bash
pytest -q tests/test_api_hardening.py
curl -i http://127.0.0.1:9100/api/v1/node/info            # 401 в строгом режиме
curl -i -H "Authorization: Bearer <ro>" .../node/info    # 200
curl -i -X POST -H "Authorization: Bearer <ro>" .../tasks # 403
```

## Не покрыто (следующие волны)

- `handle_run_script` (`/tmp/agent_loop.py`, `--iters` 500) — Волна 3+ (песочница уже здесь: `swarm.tools_runtime.tool_sandbox`);
- `_handle_config` маскирует только `llm.keys` — расширить в Волне 3;
- `int(port)` → 500 в spawn — мелочь, по ходу.
