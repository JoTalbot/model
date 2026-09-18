# AGENTS.md

## Глобальные правила для всех ИИ-агентов

> **Эти правила обязательны для любого ИИ-агента (Cursor, Arena.ai, Codex, Claude и т.д.).**

### 🌐 Язык общения

- **Всегда отвечай на русском языке.** Комментарии в коде, сообщения, объяснения, commit-сообщения — всё на русском.
- Исключение: имена переменных, функций, классов, docstrings в коде — на английском (Python convention).

### 📦 Архивация рабочего пространства

- **После каждого успешного прохождения финальных тестов** (`python3 -m pytest -q` — все зелёные) **создавай архив** рабочего пространства:

```bash
cd /home/user
zip -r gemaxi_workspace.zip gemaxi_clean/ \
    -x "gemaxi_clean/.git/*" \
    -x "gemaxi_clean/__pycache__/*" \
    -x "gemaxi_clean/**/__pycache__/*" \
    -x "gemaxi_clean/.swarm_scratch/*" \
    -x "gemaxi_clean/.pytest_cache/*"
```

- Архив нужен для переноса работы в новую среду. Делай его **чаще, не реже**.
- Если реализована крупная фича и тесты прошли — архивируй сразу.

---

## Инструкции для ИИ-агентов (Cursor Cloud / Arena.ai Agent Mode)

### Project overview

"Immortal Swarm" / "Бессмертный Рой" — распределённая P2P-сеть автономных ИИ-агентов, чистый Python (без Docker, без баз данных). См. `README.md` для архитектуры и справочника команд.

**Текущий статус (2026-05-15):** Фазы 1-3 завершены, 970 тестов + ruff clean проходят. См. `PROGRESS.md` для деталей и следующих шагов.

### Key commands

| Действие | Команда |
|---|---|
| Спек → реализация (локально) | См. `docs/spec-to-implementation.md`; черновики в `docs/plans/` |
| Установить зависимости | `pip install -r requirements.txt` |
| Запустить тесты | `python3 -m pytest -v` |
| Smoke (pytest + optional network) | `python3 scripts/swarm_smoke.py` |
| Запустить ноду | `python3 node.py start --port 8000` |
| Memory insert | `python3 node.py memory insert --table T --data '{...}'` (e.g. `--store pasters` без ключей; paste.ee нужен `PASTE_EE_API_KEY`) |
| Memory query | `python3 node.py memory query --table T --json` |
| Векторный поиск | `python3 node.py memory vector-search "query" --top 5` |
| Парсинг URL | `python3 node.py parse URL [--json]` |
| Парсинг (поиск) | `python3 node.py parse "query" --search --limit 5` |
| Health probe | `python3 node.py memory doctor --ref ref:... --json` |
| Веб-дашборд | `python3 node.py memory dashboard --demo --port 9100` |
| SQL зеркало | `python3 node.py memory sql-sync --out mirror.db` |
| RAG промпт | `python3 node.py memory rag "QUERY" --top 5` |
| ZK загрузка файла | `python3 node.py memory zk-upload PATH --replication 3` |
| QR bootstrap | `python3 node.py memory bootstrap-qr --data 'zk:...#key=...'` |
| Telegram бот | `TELEGRAM_BOT_TOKEN=... python3 node.py memory tg-bot --allow <chat_id>` |
| Очистка / GC | `python3 node.py memory consolidate --ttl 86400 --apply` |
| Заметки (быстрые) | `python3 node.py note add "текст" --tag тег --title "Заголовок"` |
| Список заметок | `python3 node.py note list` |
| Поиск заметок | `python3 node.py note search "запрос"` |
| **Архивация** | `cd /home/user && zip -r gemaxi_workspace.zip gemaxi_clean/ -x ".../__pycache__/*" -x "*/.git/*"` |

### Текущий прогресс и следующие шаги

См. `PROGRESS.md`:
- ✅ Завершённые этапы (анализ, зависимости, тесты, CLI)
- 📊 Полный анализ проекта (архитектура, фазы, метрики)
- 🔍 Приоритизированный бэклог (P0/P1/P2)
- 📌 Последняя завершённая фича: **Local LLM docs + aliases** (970 тестов + ruff clean)
- 🔄 Инструкция для продолжения в новом окружении

### Приоритизированный бэклог (сводка)

| Приоритет | Фича | Статус | Спек |
|----------|---------|--------|------|
| **P0** | Web Parser Pipeline | ✅ Реализовано | `docs/superpowers/specs/2026-05-13-web-parser-pipeline-design.md` |
| **P0** | Local LLM docs + aliases | ✅ Реализовано | `docs/plans/2026-05-15-llm-local-fallback.md` |
| **P0** | Business: автостёкла | ✅ MVP реализован | `docs/plans/2026-05-15-business-autoglass.md` |
| **P1** | Transport privacy (Tor/I2P) | ✅ V2 реализовано | `docs/plans/2026-05-15-transport-privacy.md` |
| **P1** | CRDT multi-device sync | ✅ Реализовано | — |
| **P1** | Cold storage (IPFS/Arweave) | ✅ Реализовано | `config.yaml` → секция `immortal` |
| **P2** | Desktop/Mobile (Tauri) | Не начато | — |
| **P2** | Multi-modal (изображения/голос) | ✅ Реализовано | — |
| **P2** | Линтер (ruff) | ✅ Настроен | — |

### Важные нюансы (gotchas)

- Используй `python3`, не `python` (последний не в `$PATH` в Cloud VM).
- Линтер не настроен в репозитории; нет `ruff`, `flake8`, `mypy`.
- Тесты полностью офлайн — все внешние сервисы (LLM, cloud paste, Kademlia) замоканы. API-ключи не нужны для `pytest`.
- P2P-нода привязывает три UDP/TCP-порта: Kademlia на `port`, Gossip на `port+1000`, RPC на `port+2000`. Порт по умолчанию — 8000.
- `config.yaml` содержит плейсхолдер API-ключ (`sk-or-v1-REPLACE...`). Настоящие ключи OpenRouter нужны только для `chat` и `task`; все остальные команды CLI и тесты работают без них.
- Опциональный `network.outbound_proxy` маршрутизирует **httpx** (LLM, memory facade, cloud/http links) через HTTP(S) или SOCKS; `requirements.txt` включает `httpx[socks]` для SOCKS (Tor). P2P (Kademlia/gossip/RPC) не использует этот прокси.
- `pytest.ini` устанавливает `asyncio_mode = auto` — все async-тесты запускаются без дополнительных маркеров.
- `.swarm_scratch/` — директория локального хранилища, создаётся при операциях с памятью; безопасна для gitignore.
- Опциональный mDNS/zeroconf: установи `requirements-mdns.txt` и включи `mdns.enabled: true` в `config.yaml`.
- **PROGRESS.md** отслеживает прогресс рабочих сессий — **читай его первым при возобновлении работы**.
