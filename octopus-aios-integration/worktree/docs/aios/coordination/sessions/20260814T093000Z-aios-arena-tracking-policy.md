# Сессия: JSON/source tracking policy и краткий формат общения

---
session_id: "20260814T093000Z-aios-arena-tracking-policy"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T09:30:00Z"
updated_utc: "2026-08-14T09:55:00Z"
branch: "agent/20260814-tracking-policy"
base_commit: "3c166ab1"
claim: "none (claim closed and removed after implementation)"
---

## Цель и результат

Глобальные ignore-правила заменены точечными, безопасные source/config возвращены в Git, а краткий формат общения агента с оператором закреплён в `AGENTS.md` и coordination protocol.

## Исходные факты

- 1 327 ignored JSON; только 24 скрывались глобальным `*.json`.
- 18 из них — runtime/backup/business snapshots; получили точечные ignore patterns.
- Шесть безопасных JSON manifests/dashboard должны отслеживаться.
- Глобальный `build/` скрывал 41 исходный файл `skills/stitch/build`.
- Предварительный redacted scan 47 source/config файлов: Gitleaks 0 утечек.

## Изменения

- Удалён глобальный `*.json`.
- Добавлены узкие patterns для backup, key cleanup, coverage, CatBoost и warehouse business snapshot.
- Добавлено исключение `!/skills/stitch/build/**` только для исходной Stitch-категории.
- В Git возвращены 41 Stitch build-source файл и 6 безопасных JSON manifests/dashboard.
- Добавлены `docs/TRACKING_POLICY.md`, `scripts/check_tracking_policy.py`, `tests/test_tracking_policy.py`.
- В `AGENTS.md` записано обязательное правило: краткая цель до tool-группы, только этапный статус, краткий итог; сырые логи сохранять в артефакте/session.
- То же правило добавлено в `coordination/README.md`.

## Проверки

- `[PASS]` tracking contract: 0 ошибок, 41 Stitch source file, 6 required JSON manifests, 11 runtime ignore samples.
- `[PASS]` 12 целевых contract tests.
- `[PASS]` AGENTS integration 4/4.
- `[PASS]` Gitleaks staged scan: 0 leaks.
- `[PASS]` `git diff --check`; trailing whitespace очищен в 10 импортированных source/example files.
- `[PASS]` unsafe paths (`backups/`, `data/`, `Calls/`, warehouse pricelist, coverage, CatBoost) не индексировались.

## Git

- Claim commit: `57a31cd7`.
- Implementation commit: `b75c7c14` (`fix(repo): replace broad ignores with tracking policy`).
- Финальный coordination commit находится следующим в истории.

## Handoff

- Последняя точка: JSON/source tracking risk закрыт и автоматически проверяется.
- Следующий шаг: сделать 6 failing tests герметичными — исключить live LLM, абсолютный `/root/AIOS` и зависимость от ignored runtime data.
- Чужие LLM proxy файлы основного worktree не изменялись.
