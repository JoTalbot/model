# Wave 3 — triage (items 4, 7+9)

Порт TG-команд + дайджестов (срез A), 80 скиллов + loader, подготовленный мост
memory-search. Всё paper/dry-run; юниты — файлами, disabled; команды бота —
за флагом `OCTOPUS_TGBOT_QUANT=1`.

## 1. Срез A `swarm/tgbot/` (18 модулей + `support/` 4 + `bot_commands.py`)

| Модуль | Назначение |
|---|---|
| common, credentials, state, paths, keyboards | ядро: запуск хелперов, секреты, состояние, пути, клавиатуры |
| quant_cmds, trading_report | команды /quant /ab /basket /scoreboard, снапшот /digest (HTML → мост в Markdown) |
| redaction, metrics, metrics_exporter, generation_queue, outbox | вывод: redact секретов, метрики, очередь генерации, outbox |
| llm, inbox, inbox_router, api, dashboard, crypto_store | LLM-вызовы, инбокс, роутер, TG API-клиент, дашборд-пути, шифр-стор |
| support/llm_balancer, support/llm_gemini_web | жирный балансировщик AIOS + Gemini Web (временно, см. BALANCER_MERGE_SPEC.md) |
| support/system_knowledge, support/quant_ab_report | справка для LLM, A/B-отчёт quant |
| bot_commands (NEW) | мост: `html_to_markdown()` + 5 обёрток `*_text(rest)` для SYNC_MAP |

Импорты переписаны: `tg_bot.*` → `swarm.tgbot.*`, `aios_core.*` → `swarm.tgbot.support.*`.
Все импорты support-модулей — ленивые (внутри функций): `import bot_commands`
тянет только stdlib (+ requests через api.py при первом обращении к TG API).

## 2. Адаптации путей (везде env, дефолты — продовые)

- Корень репо: `$OCTOPUS_ROOT` (def `/opt/octopus`); данные: `$OCTOPUS_DATA_DIR` (def `/var/lib/octopus`)
- Python: `sys.executable`; секреты: `$OCTOPUS_CREDENTIAL_SOURCE_DIR` (def `/etc/octopus/credentials`), systemd-credentials первичны
- `.llm_keys.json` → `$OCTOPUS_DATA_DIR`; colab-mode → `/etc/octopus/colab-mode`
- SERVICES `aios-*` → `octopus-*`; `system_knowledge` сканирует `$OCTOPUS_ROOT`, кэш — в `$OCTOPUS_DATA_DIR/system_knowledge.json`
- dashboard: `$OCTOPUS_ENV_FILE`; `aios_weekly_digest`: quant-скрипты → `scripts/aios/`, `cwd=ROOT`
- `quant_ab_report`: REPO_ROOT→DATA, убран sys.path-хак, `.env` → `$OCTOPUS_ENV_FILE`
- `dca_chart_report`: matplotlib — ленивый импорт (в venv его нет; без него `--send` шлёт только текст)
- `memory_api.py` (skill, 2 копии): DB → `$OCTOPUS_MEMORY_DB` (def `/var/lib/octopus/memory_skill.db`) + mkdir parents
- Проверка: `grep -rn "/root/AIOS|/opt/aios|/etc/aios" --include="*.py"` по порту — 0 (кроме skills, см. §5)

## 3. Апстрим-баги, исправленные в порте

1. **`dca_telegram_report.py` — строка «Контроль (DCA)» терялась всегда.** В апстриме
   `lines.append(...)` выполнялся ДО `lines = [...]` → NameError глотался `except: pass`.
   В порте строка считается в `control_line` и добавляется после `lines = [...]`.
2. **`system_knowledge.py` — мёртвый `tg_lines`** (собран, нигде не читается; `nl_lines`/`ad_lines`
   тоже только append'ятся). Удалена только flagged-строка; остальное — как в апстриме.
3. **`quant_cmds.py` — мёртвый локал `bm`** (`best_momentum` читался, не использовался). Удалён.
4. **`trading_report.py` — `zip()` без `strict=` (2 места).** Оставлено `strict=False`
   с комментариями (= поведение апстрима). Запах: в build_snapshot длины списков могут
   различаться при не-dict значениях → пары ex/pos могут быть неверны. Логику не меняли.
5. **`llm_gemini_web.py` — lock-файл.** SIM115 (open без with) подавлен через `noqa`:
   файл намеренно держится открытым (flock), `with` сломал бы межпроцессный замок.

## 4. Скрипты `scripts/aios/` (5 шт) + юниты (4 пары, disabled)

- `run_dca_paper.py` (stdlib; DCA_CONFIG: `dca_portfolio` | `dca_portfolio_control`),
  `dca_telegram_report.py`, `dca_chart_report.py` (mpl-optional),
  `run_digest.py` (xvfb-run + run_account_control — внешний раннер Wave 5+),
  `aios_weekly_digest.py` (сводка DCA/quant; OLX-часть вырезана в Wave 5)
- Юниты: `octopus-dca-paper[.service+.timer]`, `octopus-dca-paper-control`,
  `octopus-dca-report` (ExecStart ×2: telegram + chart), `octopus-digest`
  (EnvironmentFile `-` optional, логи в `/var/log/octopus/digest.log`).
  Файлы-only, не enable'ить до Wave 5 (нужны данные quant/DCA в DATA_DIR).
- **Исключено в Wave 5:** `run_market_digest.py`, `run_weekly_digest.py` (+ юнит
  `octopus-weekly-digest`) — оба читают `data/olx_http.sqlite` (item 15, маркетплейсы).

## 5. Скиллы `swarm/skills/` (80 шт, ~410 файлов, docs as-is)

Состав: всё `skills/memory/*` + все `octopus-*` + `market-rate-calculator`,
`federated-marketplace`, `skill-marketplace-sync`, `e2e_crypto` (каноничный;
близнец `e2e-crypto` — подмножество, пропущен). `loader/` + отфильтрованный
`index.json` (80/80). Структура `code/run.py` сохранена (SKILLS_ROOT=parents[3]).

- Код адаптирован только там, где ломалось: `memory_api.py` (DB, см. §2).
- Остатки `/mnt/agents` в скиллах: только graceful `CHECK_PATHS`/фолбэки —
  сканировано, записей нет (кроме исправленного memory_api).
- 82 skill-теста портированы, но НЕ в CI: гонять отдельно после Wave 5.
- `skills_loader_v3.py:170` читает `index.json` (отфильтрован, timestamp UTC).
- Ruff CI скиллы не покрывает (только явные пути); формат — как в апстриме.

## 6. Бот: `octopus-tg-bot.py` + `requirements.txt`

- SYNC_MAP += `/quant /digest /ab /basket /scoreboard` за флагом
  `OCTOPUS_TGBOT_QUANT=1` (ленивый импорт в handler'е; allowlist ALLOW_IDS
  наследуется; help extended). `call_command(fn, rest, timeout=25)` — обёртки
  совместимы. tg_send: Markdown + fallback в plaintext при reject'е.
- `requirements.txt` += `requests>=2.31` (в venv уже 2.34.2; фиксируем зависимость
  `swarm/tgbot/api.py`).
- `cryptography` (generation_queue/outbox/crypto_store) — в venv проверить на гейте.
- Прод запускает копию `/opt/octopus/octopus-tg-bot.py`: перенос туда — отдельный
  deploy-шаг, НЕ часть волны.

## 7. Memory-search: подготовлен, НЕ подключён

`scripts/aios-bridge/memory_search.py` — `search()` + FastAPI-роутер поверх
`search_memory` скилла. Ничего его не импортирует. Процедура opt-in —
`docs/aios/MEMORY_SEARCH_REPLACEMENT.md`.

## 8. Тесты и CI

- NEW `tests/test_tgbot_bridge.py` (15 тестов): конвертер HTML→Markdown (9 кейсов),
  флаг вкл/выкл, 4 quant-команды + digest на пустом DATA_DIR, офлайн-гарантия
  (socket.create_connection/socket → AssertionError).
- CI: в `test.yml`/`security.yml` добавлены ruff-пути
  `swarm/tgbot/ scripts/aios/ scripts/aios-bridge/ tests/test_tgbot_bridge.py`
  и pytest `tests/test_tgbot_bridge.py`; в `production-gate.yml` — ruff `swarm/tgbot/`.
- Ruff: проектный конфиг (E W F I UP B SIM RUF) — 0 ошибок на новом коде.
  Стартовые 102 → автофикс 63 → 41 вручную (E741 `l`→`line`, RUF005, SIM105,
  RUF059, F841, B905 strict=False, SIM102, E731, SIM115 noqa, UP031, RUF046).
- Skill-тесты (82) и портированные AIOS-тесты tgbot — вне CI этой волны.

## 9. Отложено (следующие волны)

- Wave 4 (item 1): quant-движок paper — даст реальные данные для /quant /ab /basket.
- Wave 5 (items 2,3,5,6,8b,15,19,20): freqtrade, коллекторы, ML, DeFi(код), слияние
  балансировщика (убрать `support/llm_balancer.py`), OLX-дайджесты (+ weekly-юнит),
  доки, дашборды; тогда же — enable юнитов §4 и skill-тесты в CI.
- Не портировано из tg_bot (позже): callbacks/accounts/phone/freelance/voice/OLX-команды.
