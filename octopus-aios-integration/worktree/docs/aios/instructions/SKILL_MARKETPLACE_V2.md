# SKILL_MARKETPLACE_V2 — Магазин навыков

## Архитектура
- **Source of Truth:** Папка `~/agents/-Octopus/skills/`.
- **Index:** `index.json` со списком доступных скиллов и их версий.
- **Distribution:** GitHub репозитории или Nostr события.

## Структура скилла (.skill)
- `SKILL.md` — Описание и инструкции.
- `manifest.yaml` — Зависимости и триггеры.
- `code/` — Исполняемый код (Python/Bash).
- `tests/` — Тесты для верификации.

## Команды (план)
- `octopus skill list` — Показать доступные.
- `octopus skill install <name>` — Установить.
- `octopus skill update <name>` — Обновить.
