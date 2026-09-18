# Memory-search: замена AIOS-роутера (подготовлена, не применена)

Статус Wave 3: файл `scripts/aios-bridge/memory_search.py` положен в репо,
ничего его не импортирует. Замена включается отдельно (opt-in), прод не затронут.

## Что было в AIOS

`memory_search_router` — тонкий FastAPI-роутер (~19 строк) поверх поиска по памяти,
с `sys.path`, указывающим на `/mnt/agents/...`. В Octopus такой путь мёртв:
память скилла живёт в `$OCTOPUS_MEMORY_DB` (def `/var/lib/octopus/memory_skill.db`,
см. WAVE3_TRIAGE.md §2), движок — `search_memory()` скилла `pwa-file-exchange`
(LIKE по title/content/tags, сортировка по modified_at, лимит 50).

## Что подготовлено

`scripts/aios-bridge/memory_search.py`:

- `search(query, limit=20) -> list[dict]` — грузит скилл через importlib по пути
  `$OCTOPUS_ROOT/swarm/skills/memory/pwa-file-exchange/code/memory_api.py`,
  режет до `limit`. Только stdlib.
- `create_router()` — FastAPI APIRouter `POST /memory/search` (`{"query","limit"}`).
  `fastapi`/`pydantic` импортируются лениво внутри функции.
- CLI: `python scripts/aios-bridge/memory_search.py "<запрос>"` → JSON.

## Как включить (когда понадобится, Wave 5+)

1. Убедиться, что DB существует и наполнена:
   `OCTOPUS_MEMORY_DB=/var/lib/octopus/memory_skill.db python scripts/aios-bridge/memory_search.py test`
2. В `swarm/api/` (или где живёт приложение FastAPI) добавить:
   `app.include_router(memory_search.create_router())`
   (импорт — по пути файла через importlib, либо перенести модуль в `swarm/`).
3. Перезапустить API, проверить `POST /memory/search`.
4. Старый AIOS-роутер нигде в Octopus не существует — удалять нечего.

## Миграция данных (разово, вручную)

Если в `/mnt/agents/.../memory.db` на AIOS-хосте есть ценные записи — перенести файл:
`scp /mnt/.../memory.db octopus:/var/lib/octopus/memory_skill.db`
(схема совпадает: таблица `memory_items`). Права: чтение пользователю API.
В Wave 3 миграция НЕ выполняется.
