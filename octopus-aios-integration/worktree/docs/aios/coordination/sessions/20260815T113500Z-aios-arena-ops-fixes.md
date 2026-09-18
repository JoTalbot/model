---
session_id: "20260815T113500Z-aios-arena-ops-fixes"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-15T11:35:00Z"
updated_utc: "2026-08-15T12:00:00Z"
branch: "agent/20260814-quant-backfill-ppo"
base_commit: "fd386142"
claim: "coordination/claims/ops-fixes--20260815T113500Z-aios-arena-ops-fixes.md (removed on DONE)"
---

## Цель

Устранить restart-loop `aios-groq-key`, снизить заполнение диска и синхронизировать
`PROJECT_CONTEXT.md` с фактическим runtime.

## Scope

- Разрешено: systemd-состояние `aios-groq-key`, disposable-кэши, `scripts/cleanup_disk.sh`,
  `deploy/systemd/HETZNER_MASKED_UNITS.txt`, `tests/test_systemd_inventory.py`, координационные файлы.
- Явно вне scope: quant-конфигурация, пороги owner-профиля, live-торговля, Ollama-модели,
  удаление бэкапов в пределах политики хранения, protected-файлы.
- Пересечения: активный claim `paper-fix` (quant) — не затрагивался.

## Ход работы и решения

### Фикс 1 — restart-loop `aios-groq-key.service`

Root cause: `ExecStart=/root/AIOS/groq_key_retry.py`, файла нет ни в ФС, ни в git-истории
(`git log --all -- groq_key_retry.py` пусто) — временный скрипт был потерян, unit остался enabled.
Счётчик рестартов на момент вмешательства — 7832 (~2833/сутки, каждые 30с).

Проверено перед действием: преемник `aios-groq-autopilot.timer` установлен, enabled, отрабатывает
ежечасно со `status=0/SUCCESS`, выдаёт `{"keys": 8, "action": "none"}`. То есть функция добычи/ротации
Groq-ключей уже покрыта, а legacy-unit — чистый мусор.

Решение: `stop` + `disable` + `mask` (симлинк на `/dev/null`). Mask выбран вместо удаления как
обратимая операция и уже существующая конвенция хоста (`HETZNER_MASKED_UNITS.txt`).
Base unit сохранён в `backups/systemd_20260815/` (плюс tracked-копия в `deploy/systemd/`,
diff подтвердил идентичность перед удалением файла из `/etc`).

Верификация: за 2 минуты после mask — 0 новых записей в журнале, `is-active=inactive`,
`is-enabled=masked`, `systemctl --failed` пуст, преемник не задет.

### Фикс 2 — диск

Важное уточнение к вчерашнему анализу: AIOS занимает лишь 6.5G из 60G занятых.
Основные потребители — вне репозитория:

- `/var/lib/docker/rootfs/overlayfs` — 17G (образы, `docker system df` показывает 0B reclaimable);
- `/usr/share/ollama` — 14G (5 локальных моделей, сервис active/enabled, используются `llm_router.py`);
- `/opt/android-sdk` — 8.7G; `/var/lib/containerd` — 6.3G.

Проверено, что бэкапы AIOS удалять нельзя: `backups/daily` — 5 дней при политике 14д,
`backups/sessions` — 5 копий при retention 7, `messenger_profiles` — 9 при retention 14.
Все в пределах собственной политики проекта, ротация работает.

Освобождено только disposable: apt cache, crash dumps >7д, 3 отключённые snap-ревизии,
`/root/.cache/pip-tools` (649M) и `pip` (33M), `/tmp` >2д (1746 файлов), `__pycache__`.
Итог: 83% → 81% (13G → 14G свободно).

Чтобы не росло снова, в `scripts/cleanup_disk.sh` (запускается таймером `aios-disk-cleanup`,
ежедневно 02:00) добавлена очистка regenerable-кэшей, crash dumps и apt cache.

Не тронуто намеренно: Ollama-модели (14G) и Docker-образы (17G) — используются; их сокращение
это решение владельца, а не рутинная очистка.

### Фикс 3 — синхронизация контекста

`PROJECT_CONTEXT.md` утверждал `freeze`, фактически в unit `AIOS_QUANT_ENTRY_MODE=enabled`
(owner-approved constrained profile от 2026-08-14T12:20Z). Формулировка исправлена, добавлен
верифицированный срез: за 18ч trades=0, `exchange_not_allowed`=96 на скан (allowlist
`kucoin,bitstamp,mexc` против универсума 33 активов — отсечение до ML-гейта).
Записано operator decision по `aios-groq-key`.

## Изменённые файлы

- `deploy/systemd/HETZNER_MASKED_UNITS.txt` — добавлен `aios-groq-key.service`, дата снапшота.
- `tests/test_systemd_inventory.py` — ожидаемый набор masks приведён к фактическому.
- `scripts/cleanup_disk.sh` — +6 строк: pip/pip-tools cache, crash dumps >7д, apt clean.
- `coordination/PROJECT_CONTEXT.md` — entry_mode drift, quant-срез, operator decision.

Runtime (вне Git): `aios-groq-key.service` masked; backup в `backups/systemd_20260815/` (не tracked).

## Проверки

- `[PASS]` `systemctl is-active/is-enabled aios-groq-key` — inactive / masked.
- `[PASS]` журнал за 2 мин после mask — 0 новых рестартов (было ~120/час).
- `[PASS]` `systemctl --failed` — пусто.
- `[PASS]` `systemctl list-timers aios-groq-autopilot` — active, next 12:00, преемник цел.
- `[PASS]` `python scripts/audit_deployment_sources.py --runtime` — drift 0, errors 0 (до и после).
- `[PASS]` `pytest tests/test_systemd_inventory.py -q` — 3 passed (был 1 failed после mask).
- `[PASS]` `ruff check tests/test_systemd_inventory.py` — All checks passed.
- `[PASS]` `bash -n scripts/cleanup_disk.sh` — синтаксис ок.
- `[PASS]` `python run_health_check.py` — 21/22, диск 81% (было 83%).
- `[NOT RUN]` полный `pytest tests/ -q` — не запускался; затронуты только systemd-inventory тесты.

## Git

- Коммит: см. ниже в ветке `agent/20260814-quant-backfill-ppo`.
- Незакоммиченные изменения: `backups/systemd_20260815/` намеренно не добавлен в индекс
  (физический runtime-артефакт, политика #8 — такие файлы не tracked).
- Чужие изменения: отсутствовали; claim `paper-fix` не затронут.

## Handoff

- Последняя завершённая точка: три фикса применены и верифицированы, тесты зелёные.
- Следующий конкретный шаг: решение владельца по диску — 81% всё ещё выше комфортного порога,
  а основной резерв это Ollama-модели (14G) и Docker-образы (17G). Без их сокращения
  или расширения диска health-check продолжит помечать красным.
- Блокеры: нет.
- Риски: диск снизился незначительно; крупные потребители не тронуты сознательно.
- Что нельзя без повторной проверки: удалять Ollama-модели и Docker-образы (используются
  в проде), включать live-торговлю, менять пороги owner-профиля, снимать mask
  без восстановления `groq_key_retry.py`.
