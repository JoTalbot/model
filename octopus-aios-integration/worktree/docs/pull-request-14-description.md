**Рекомендуемый merge:** [PR #16](https://github.com/JoTalbot/gemaxi/pull/16) — тот же Phase 3, **ребейз на актуальный `main`**, плюс харднинг Telegram (нужен `--allow` или явный `--open-access`). После мержа #16 этот draft можно закрыть.

> **Архивный снимок:** цифры тестов и тайминги ниже — на момент составления описания Phase 3. Актуальное число тестов всегда смотри в своём дереве: `python3 -m pytest -q` (после последующих коммитов, например shard repair RPC, ожидай порядка **511+** passed).

---

## Что это

Большая интеграционная ветка Phase 3 поверх 4 предыдущих PR (#10 E2E encryption, #11 Ed25519 signatures, #12 smart routing, #13 FileDropbox). 12 новых модулей, **~505 тестов** на момент описания (было 250 на main → +255), **+5 cloud-адаптеров** (теперь 19 анонимных бесплатных хранилищ), всё работает offline без API-ключей.

> Эта ветка **включает** в себя коммиты PR #10/#11/#12/#13. Если хочешь — слей их сначала, потом merge'ни эту; либо мержи только её и она затянет всё одним махом.

## Что внутри (по фазам)

### 🔒 Phase 3a + 3k — Security & privacy
- `swarm/memory/audit.py` + `AuditedMemoryPort` — JSONL audit-log с daily rotation, фильтрами по op/ref/scheme/ok/agent/time, агрегатами per-op / per-scheme. Сбои лога не ломают memory-операции.
- `swarm/memory/zk_dropbox.py` — zero-knowledge dropbox: AES-256-GCM на клиенте, ключ в URL fragment (`zk:...#key=...`). Пастебины держат только шифротекст. Тест проверяет что НИ ОДНОГО байта плейнтекста не утекает в симулированные облака.

### 📦 Phase 3a — Ещё 5 cloud-paste адаптеров
- `PixelDrainAdapter` — pixeldrain.com (20 GB, anonymous, постоянное хранение пока просматривается)
- `FilebinAdapter` — filebin.net (bin-style, supports delete)
- `LitterboxAdapter` — litterbox.catbox.moe (1h/12h/24h/72h temp)
- `BashuploadAdapter` — bashupload.com (PUT-based, 3 дня)
- `ClbinAdapter` — clbin.com (text, ix.io-альтернатива)

### 🌐 Phase 3d — Sneakernet recovery
- `swarm/memory/qr.py` + `memory bootstrap-qr` — терминальный QR из любой короткой строки (ref / zk-link). Скан с любого телефона. ECC-уровень настраиваемый.

### 📊 Phase 3c + 3e + 3g — Observability & ops
- `swarm/memory/doctor.py` + `memory doctor` — bulk `exists()` probe с per-scheme summary и латентность p50/p95. Exit-code 1 при сломанных — CI-friendly.
- `swarm/memory/prom.py` — Prometheus exposition без `prometheus_client` (зависимости не нужны). Поддерживает audit_stats counters.
- `swarm/memory/dashboard.py` — stdlib-only `http.server`: `/`, `/metrics`, `/api/metrics`, `/api/audit`, `/healthz`. Никакого aiohttp / Flask. Скриншот в Walkthrough ниже.
- `swarm/memory/consolidate.py` + `memory consolidate` — TTL GC + exact-duplicate (blake2b) + near-duplicate (Jaccard 4-grams). Plan-then-apply с `keep_newest`.

### 🗄 Phase 3f — SQL gateway
- `swarm/memory/sql_gateway.py` — `SqlMirror` строит SQLite-проекцию `MemoryRepository` (таблицы `records` + `record_tags`). Запускай `sqlite3 mirror.db "SELECT ... JOIN ..."` напрямую.

### 🧠 Phase 3i — RAG
- `swarm/memory/rag.py` — `Retriever` (top-K cosine) + `HybridRetriever` (vector∪tag), `build_prompt()` с inline `[N]` цитатами. LLM-agnostic — генерация живёт в `swarm/llm/`.

### 📱 Phase 3l — Phone-side control
- `swarm/memory/telegram.py` — long-polling бот **БЕЗ python-telegram-bot**, использует уже имеющийся `httpx`. Allowlist по `chat_id` (в **PR #16** усилено: пустой allowlist = ни один чат; нужен `--allow` или явный `--open-access` в CLI). Команды: `/status`, `/list`, `/insert`, `/rag`, `/qr`.

## Walkthrough

### Web dashboard
[memory dashboard rendering metrics](https://cursor.com/agents/bc-3f5cae55-bc24-4573-9eb6-7f38c3bba3f3/artifacts?path=%2Fopt%2Fcursor%2Fartifacts%2Fmemory_dashboard.png)

`python node.py memory dashboard --demo --port 9100` запускает stdlib-only HTTP-сервер с тёмной темой, mobile viewport и таблицей метрик — открывается из браузера телефона.

### QR-код для sneakernet recovery
```
█████████████████████████████████████
██ ▄▄▄▄▄ █ ▄▀▄▄█▄██▀▄▀█▀▀█▀█ ▄▄▄▄▄ ██
██ █   █ █▄▀▄▄████▄▄▄ ██▄█▀█ █   █ ██
██ █▄▄▄█ █▄▄▄▀▀  ▄█▀▄█ ▄█  █ █▄▄▄█ ██
██▄▄▄▄▄▄▄█▄▀▄█▄▀▄█▄█ ▀ █▄▀▄█▄▄▄▄▄▄▄██
...
```
`python node.py memory bootstrap-qr --data "ref:catbox:https://files.catbox.moe/abc.json"` — фотка телефоном восстанавливает доступ.

### End-to-end demo команды
```bash
# Insert 3 rows, mirror to SQLite, run SQL JOIN
python node.py memory insert --table notes --data '{"text":"hello"}' --tags wiki
python node.py memory sql-sync --out mirror.db
python node.py memory sql-query "SELECT r.ref, t.tag FROM records r JOIN record_tags t USING(ref)" --db mirror.db

# Bulk health-check
python node.py memory doctor --ref ref:file:<id> --ref ref:file:dead --json

# RAG over vector index
python node.py memory vector-add --id g1 --text "lobovoe steklo BMW X5 Pilkington"
python node.py memory rag "Какое стекло у BMW X5?" --top 3

# Zero-knowledge upload
python node.py memory zk-upload backup.zip --replication 3
# → zk:dropbox:ref:catbox:https://...#key=AbCd...

# Cleanup
python node.py memory consolidate --ttl 86400 --apply
```

Все эти команды реально прогнаны в smoke-тестах в коммитах ниже — ссылки и логи в commit messages.

## Тесты

**~505 passing** на момент описания (250 на main → +255); разбивка по файлам ниже — для истории Phase 3.

| Phase | Тестов | Файл |
|---|---|---|
| 3a (5 adapters) | +30 | `tests/test_paste_cloud_extra.py` |
| 3b (audit) | +24 | `tests/test_audit.py` |
| 3c (doctor) | +16 | `tests/test_doctor.py` |
| 3d (qr) | +11 | `tests/test_qr.py` |
| 3e (prom) | +11 | `tests/test_prom.py` |
| 3f (sql gateway) | +14 | `tests/test_sql_gateway.py` |
| 3g (dashboard) | +10 | `tests/test_dashboard.py` |
| 3i (rag) | +16 | `tests/test_rag.py` |
| 3j (consolidate) | +17 | `tests/test_consolidate.py` |
| 3k (zk dropbox) | +14 | `tests/test_zk_dropbox.py` |
| 3l (telegram) | +16 | `tests/test_telegram.py` |
| (+ included from #10/#11/#12/#13) | +76 | crypto / signing / routing / dropbox |

Все офлайн, без сети, без API-ключей. Актуальный итог: `python3 -m pytest -q` (в свежем merge с shard repair — **511 passed** за ~70s в типичном окружении).

## Новые зависимости

- `qrcode>=7.4` — pure-Python, MIT, для QR-кодов (без Pillow в ASCII-режиме)
- `cryptography>=42.0` — уже было от #10, дополнительно используется в zk_dropbox

`aiohttp`, `prometheus_client`, `python-telegram-bot`, `numpy`, `tor` — **НЕ нужны**. Только stdlib + httpx + cryptography + qrcode.

## Безопасность

- `EncryptedMemoryPort` шифрует артефакты ДО того как любой адаптер их видит (AAD-bound metadata)
- `SignedMemoryPort` детектит любую подмену content / attrs / tags / mime / provenance
- `AuditedMemoryPort` пишет неизменяемый JSONL-журнал каждой операции
- `ZkDropbox`: ключ только в URL fragment, в swarm-у ВСЕГДА только шифротекст
- Telegram-бот: allowlist по `chat_id`; в PR #16 по умолчанию без `--allow` ответов нет, есть флаг `--open-access` только для лаборатории
- Dashboard HTML-escape'ит названия схем — `<bad>scheme` не XSS'ит

## Что НЕ вошло (умышленно)

- TOR/I2P transport — требует реального Tor-демона + I2P-роутера на машине. Хороший кандидат на отдельный PR с `--enable-tor` флагом.
- WebRTC datachannels — нужен `aiortc` (тяжёлая dep с C-кодом, OpenSSL и libsrtp). Отдельный PR.
- Local LLM fallback (llama.cpp) — отдельный модуль `swarm/llm/local.py`, лучше как самостоятельный PR.
- Business парсеры (Pilkington/FYG/NordGlass, VIN→стекло, OCR) — это бизнес-логика автостёкол, заслуживает отдельной ветки.

Эти направления специально оставлены на следующую итерацию — чтобы PR оставался обозримым и каждая часть имела фокус.

<sub>To show artifacts inline, <a href="https://cursor.com/dashboard/cloud-agents#my-pull-requests">enable</a> in settings.</sub>