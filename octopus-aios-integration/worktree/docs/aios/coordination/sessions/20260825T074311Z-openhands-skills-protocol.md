---
session_id: "20260825T074311Z-openhands-skills-protocol"
status: "DONE"
agent: "OpenHands (external agent)"
machine: "openhands-sandbox -> server aios (<PUBLIC_IP_REDACTED>)"
started_utc: "2026-08-25T07:43:11Z"
updated_utc: "2026-08-25T08:20:00Z"
branch: "agent/20260825T074311Z-openhands-skills-protocol/agent-skills-protocol"
base_commit: "25155a61"
claim: "coordination/claims/agent-skills-protocol--20260825T074311Z-openhands-skills-protocol.md (удалён по протоколу)"
---

## Цель

Закрепить в репозитории обязательные правила для ИИ-агентов: параллельная работа с разных
машин, видимость текущего шага, превращение лога работы в основной скилл агента,
обязательный поиск подходящего скилла (в т.ч. в интернете) и глубокое исследование
интернета и репозитория перед каждым шагом.

## Scope

- Разрешённые компоненты/файлы: AGENTS.md, docs/AGENT_SKILLS_PROTOCOL_RU.md,
  coordination/SESSION_TEMPLATE.md, coordination/sessions/<session-id>.md,
  coordination/claims/<claim>.md, skills/coder/agent-skills-protocol-bootstrap/SKILL.md
- Явно вне scope: код aios_core/octopus_core, protected files, чужие незакоммиченные
  изменения в основном worktree
- Ожидаемые пересечения с другими сессиями: нет (файлы других агентов не пересекаются)

## Текущий шаг (виден другим агентам)

- Текущий шаг: DONE — протокол задокументирован, проверки 4/4, коммит на ветке agent/20260825T074311Z-openhands-skills-protocol/agent-skills-protocol. Дальше — публикация в origin по решению владельца.
- Обновлено UTC: 2026-08-25T07:51:49Z

## Исходное состояние

- `git status --short` (основной worktree): чужие активные изменения (llm_balancer,
  quant_*, tg_bot, coordination/PROJECT_CONTEXT.md, claims/sessions других агентов) —
  НЕ затронуты; работа в отдельном worktree /root/AIOS-work/skills-protocol от HEAD 25155a61.
- Прочитанные документы: AGENTS.md, coordination/README.md, PROJECT_CONTEXT.md,
  SESSION_TEMPLATE.md, skills/TEMPLATES/SKILL.md.template, scripts/test_agents_md.py

## План

1. Claim + журнал ACTIVE.
2. AGENTS.md: новая обязательная секция (diff-вставка).
3. SESSION_TEMPLATE.md: блок «Текущий шаг (виден другим агентам)».
4. docs/AGENT_SKILLS_PROTOCOL_RU.md: детальный протокол.
5. Проверки: маркеры AGENTS.md, AutocoderV3._load_agents_md, scripts/test_agents_md.py.
6. Дистилляция сессии в skills/coder/agent-skills-protocol-bootstrap/SKILL.md.
7. Журнал DONE, claim удалён, коммит только своих путей.

## Ход работы и решения

- 07:43Z — старт, прочитаны обязательные файлы, создан worktree от HEAD 25155a61.
- Выбран worktree вместо переключения ветки в грязном общем worktree (правило coordination).
- AGENTS.md: якорная вставка новой секции «Скиллы, исследование и видимость статуса
  (ОБЯЗАТЕЛЬНО)» перед «Формат общения» (+24 строки, удалений 0). Deep research по
  шагу: локально проверены scripts/test_agents_md.py (контракт Protected/Золотые правила),
  skills/TEMPLATES; интернет-исследование не требовалось — правка структурная, не кодовая.
- SESSION_TEMPLATE.md: блок «Текущий шаг (виден другим агентам)» после «План» (+9 строк, удалений 0).
- docs/AGENT_SKILLS_PROTOCOL_RU.md: 7 разделов — видимость статуса, поиск скиллов
  локальный+интернет, дистилляция лог→скилл, deep research, чеклист, связь с правилами.
- Проверки: маркеры PASS, реальный код-путь AutocoderV3 PASS, test_agents_md.py 4/4 PASS.
- Скилл skills/coder/agent-skills-protocol-bootstrap/SKILL.md — дистилляция этой сессии.
- Claim удалён по протоколу (DONE).

## Изменённые файлы

- `AGENTS.md` — новая обязательная секция «Скиллы, исследование и видимость статуса» со ссылкой на docs-протокол.
- `docs/AGENT_SKILLS_PROTOCOL_RU.md` — детальный протокол (новый).
- `coordination/SESSION_TEMPLATE.md` — обязательный блок «Текущий шаг (виден другим агентам)».
- `skills/coder/agent-skills-protocol-bootstrap/SKILL.md` — скилл, дистиллированный из этой сессии (новый).
- `coordination/sessions/20260825T074311Z-openhands-skills-protocol.md` — этот журнал.

## Проверки

- `[PASS]` маркерная проверка: Protected, Золотые правила, новая секция, ссылка на docs.
- `[PASS]` `AutocoderV3._load_agents_md` на edited copy (repo_path=/root/AIOS-work/skills-protocol) — 11915 chars.
- `[PASS]` `/opt/aios/.venv/bin/python scripts/test_agents_md.py` — 4/4.
- `[NOT RUN]` pytest — изменения только документационные (md), код не затронут.
- `[NOT RUN]` ruff — изменены только .md.

## Git

- Коммиты: см. лог ветки (один коммит, только свои пути).
- Опубликованная ветка/PR: PR #241 https://github.com/JoTalbot/AIOS/pull/241, mergeable: True, required checks: нет. Коммит c39e162d (inventory fix).
- Незакоммиченные изменения: нет (в моём worktree).
- Чужие изменения, которые не были затронуты: все из «Исходное состояние».

## Handoff

- Последняя завершённая точка: DONE — все 5 артефактов готовы, проверки зелёные, коммит на ветке.
- Следующий конкретный шаг: по решению владельца опубликовать ветку в origin (push) и оформить PR в main.
- Блокеры: нет.
- Риски: scripts/test_agents_md.py жёстко читает /root/AIOS/AGENTS.md — после merge в main
  проверка пройдёт на сервере (блок уже выполнен pre-merge как PASS).
- Что нельзя делать без повторной проверки: push в origin и PR — без согласия владельца.
