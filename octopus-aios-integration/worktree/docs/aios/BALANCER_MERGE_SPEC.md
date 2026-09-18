# Balancer Merge Spec (Волна 1, пункт 8а — аудит, без кода)

Цель Волны 5 (8б): один балансировщик в `swarm/llm/`, удаление зависимости продового TG-бота от `/opt/aios`.

## 1. Три живые реализации + один труп

| | A. octopus `swarm/llm/` | B. `/opt/aios/llm/llm_balancer.py` ⚠️ untracked | C. fat `aios_core/llm_balancer.py` | D. fat `tools/llm_balancer.py` |
|---|---|---|---|---|
| Строк | 155 (`router` 113 + `key_pool` 42) | 479 | 1102 | 69 |
| Стиль | async, httpx | sync, urllib/requests | sync, Colab-runtime | — |
| Провайдеры | OpenRouter-пул + local (Ollama-совм.) | multi-cloud OpenAI-совм., Gemini, HF, LizaRPA, Ollama, local-fallback | Colab LLM runtime + local-fallback | — |
| API | `complete()`, `usage_snapshot()`, `close()` | `generate_sync()`, `classify_task()`, `get_stats()`, `reload_keys()`, синглтон `llm_balancer` | `chat()`, `add_key()`, `status()`, `last_route`, `refresh_runtime_config()` | **ТРУП**: unittest, импортирует сам себя — не портировать |
| Кто использует | swarm-агенты | **продовый `octopus-tg-bot.py:20`** | tg_bot/quant на fat-ветках | никто |
| Секреты | KeyPool извне | `_load_secrets()` из env | env + colab-runtime файлы | — |

## 2. Целевой дизайн `swarm/llm/` (Волна 5)

- `key_pool.py` — оставить как есть (расширить при необходимости per-provider пулами).
- `router.py` — async-ядро остаётся; добавить provider-плагины из B (Gemini/HF/Ollama/LizaRPA) как `AuthKind`/таргеты в `_target_chain`.
- `balancer.py` (новый) — sync-фасад для совместимости с B: `generate_sync(prompt, system, task_type)`, `classify_task()`, `get_stats()`, `reload_keys()`, синглтон `llm_balancer`; внутри — вызов async-ядра через `asyncio.run` (осторожно с loop в tg-bot: там уже есть loop — использовать `run_coroutine_threadsafe` или перевести вызовы на async).
- `chat()` из C — добавить как алиас к `complete()` (совместимость со скиллами/quant).
- Colab-runtime из C (`refresh_runtime_config`, `_query_colab_llm`) — **не портировать** в Волне 5 (нет Colab-инфры на проде); оставить точкой расширения.
- Секреты — только env/systemd-credentials; обобщить `_load_secrets()` из B.

## 3. Реализация (релизный батч 2026-09-18)\n\n- Канонический модуль: `swarm/llm/balancer.py`.\n- `code/llm/balancer/llm_balancer.py` оставлен как backward-compatible re-export, поэтому старые импорты не ломаются.\n- Удалена бесшумная обрезка prompt в OpenAI-compatible, Liza RPA и Ollama провайдерах.\n- Убран отдельный `cloud_only` лимит 4000 символов, который мог отбрасывать допустимые запросы до маршрутизации.\n- Auto-tuner больше не зависит от `/opt/aios`, не тестирует строгий Arena tier как обычный провайдер и оптимизирует веса только внутри одного tier.\n- Добавлен `tests/test_llm_balancer_release.py` с проверками сохранения полного prompt, fallback, emergency fallback и совместимости импорта.\n\n## 4. Тесты к портированию (Волна 5)

- `tests/test_llm_balancer_90.py`, `test_llm_balancer_v2.py`, `test_llm_balancer_v2_extra.py`, `test_llm_balancer_coverage80.py` (fat) — проверить импорты, ремап `aios_core.llm_balancer` → `swarm.llm.balancer`, моки HTTP.
- Новый `test_swarm_llm_facade.py`: sync-фасад ↔ async-ядро, fallback-цепочка, stats.

## 5. Миграция TG-бота (Волна 5, отдельным deploy-коммитом)

1. `octopus-tg-bot.py`: заменить `sys.path.insert('/opt/aios')` + `from llm.llm_balancer import llm_balancer` на `from swarm.llm.balancer import llm_balancer`.
2. Приёмка: `/aios` команды работают, в `ps`/логах нет обращений к `/opt/aios`.
3. Только после приёмки: удалить `/opt/aios/llm/*` (оставить tools/ до Волны 3).

## 6. Критерии приёмки 8б

- [ ] `grep -r "/opt/aios" octopus-tg-bot.py` пуст (кроме tool-factory вызовов — те до Волны 3)
- [x] `pytest tests/test_llm_balancer_release.py -q` покрывает новый канонический слой\n- [ ] `pytest tests/test_llm* tests/test_swarm_llm* -q` зелёный на целевом runtime
- [ ] Ни одного ключа в репо (gitleaks-гейт зелёный)
