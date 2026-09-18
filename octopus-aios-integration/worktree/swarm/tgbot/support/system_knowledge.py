"""
System Knowledge — карта возможностей AIOS для LLM-контекста и справки.

Собирает из реальных источников репозитория:
  * skills/SKILLS_INDEX.md   — каталог скилов (242 шт., по категориям)
  * aios_core/platforms/     — адаптеры платформ (классы + docstrings)
  * aios_core/modules/       — интеграции (olx, instagram, viber, ...)
  * run_*.py                 — точки входа сервисов/скриптов
  * расширенный список NL-команд (управление обычным языком)

Использование:
  * get_system_guide(prompt_mode=True) — компактная справка для промпта LLM
    (только NL-управление обычным языком + краткий обзор платформ/скилов)
  * get_system_guide(prompt_mode=False) — полная справка для /skills
  * rebuild_guide(force=True) — пересобрать вручную (кэш TTL 6 часов)

CLI:
  python aios_core/system_knowledge.py [--rebuild] [--show] [--full]
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))
CACHE_FILE = DATA / "system_knowledge.json"
CACHE_TTL = 6 * 3600  # 6 часов

# ---------------------------------------------------------------------------
# Парсинг источников
# ---------------------------------------------------------------------------

_SKILL_CAT_RE = re.compile(r"^##\s+([\w/]+)\s*\((\d+)\)\s*$")
_SKILL_ITEM_RE = re.compile(r"^-\s+\*\*`([^`]+)`\*\*\s*[—-]\s*(.+)$")


def _load_skills() -> dict[str, list[tuple[str, str]]]:
    """Разобрать SKILLS_INDEX.md -> {категория: [(имя, описание), ...]}."""
    path = PROJECT_ROOT / "skills" / "SKILLS_INDEX.md"
    cats: dict[str, list[tuple[str, str]]] = {}
    if not path.exists():
        return cats
    cur = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SKILL_CAT_RE.match(line.strip())
        if m:
            cur = m.group(1)
            cats.setdefault(cur, [])
            continue
        m = _SKILL_ITEM_RE.match(line.strip())
        if m and cur is not None:
            desc = m.group(2).strip()
            if len(desc) > 140:
                desc = desc[:140] + "…"
            cats[cur].append((m.group(1).strip(), desc))
    return cats


def _load_adapters() -> list[tuple[str, str]]:
    """Адаптеры платформ: класс + первая строка docstring."""
    out: list[tuple[str, str]] = []
    plat = PROJECT_ROOT / "aios_core" / "platforms"
    if not plat.exists():
        return out
    for f in sorted(plat.glob("*adapter*.py")) + sorted(plat.glob("*chrome_twin*.py")):
        if f.name == "__init__.py":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in re.finditer(r"^class\s+(\w+)\s*(?:\([^)]*\))?:\s*$", text, re.M):
            cls = m.group(1)
            after = text[m.end() : m.end() + 400]
            dm = re.search(r'"""\s*(.*?)(?:\n|""")', after, re.S)
            desc = dm.group(1).strip().replace("\n", " ") if dm else ""
            if len(desc) > 120:
                desc = desc[:120] + "…"
            out.append((cls, desc))
    return out


def _load_modules() -> list[str]:
    """Интеграции в aios_core/modules/ (каталоги)."""
    mods = PROJECT_ROOT / "aios_core" / "modules"
    if not mods.exists():
        return []
    return sorted(
        d.name for d in mods.iterdir() if d.is_dir() and not d.name.startswith("_")
    )


def _load_run_scripts() -> list[tuple[str, str]]:
    """run_*.py: имя + первая строка docstring."""
    out: list[tuple[str, str]] = []
    for f in sorted(PROJECT_ROOT.glob("run_*.py")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = re.search(r'"""\s*(.*?)(?:\n|""")', text, re.S)
        desc = m.group(1).strip().replace("\n", " ") if m else ""
        if len(desc) > 110:
            desc = desc[:110] + "…"
        if desc:
            out.append((f.name, desc))
    return out


# ---------------------------------------------------------------------------
# Курируемые NL-команды (управление обычным языком) — расширенный список
# ---------------------------------------------------------------------------

NL_COMMANDS: list[tuple[str, str]] = [
    # Google / почта / календарь / диск
    (
        "Google-аккаунт",
        "«проверь почту», «есть ли непрочитанные», «покажи письма», «прочитай письмо 2», "
        "«найди письмо от github», «ответь на письмо 1: текст», «отправь письмо email, тема …, текст: …» "
        "(с подтверждением), «кто я», «какой аккаунт залогинен», «покажи календарь», «события», "
        "«план на день», «события на неделю», «добавь событие Встреча завтра в 14:00», «диск», "
        "«что на диске», «создай документ …», «создай таблицу …», «скачай файл …», «контакты», "
        "«адресная книга»",
    ),
    # Instagram
    (
        "Instagram",
        "«мой инстаграм», «мой профиль», «мои посты», «скрин профиля», «подписчики», "
        "«подпишись на @…», «отпишись от @…», «лайкни <ссылка>», «комментарии», "
        "«ответь на комментарий …», «директ», «покажи чат <имя>», «напиши в директ <имя>: текст», "
        "«директ», «чаты в инстаграм», «сторис»",
    ),
    # OLX
    (
        "OLX",
        "«создай объявление <деталь>», «опубликуй на олх …», «опубликуй это объявление», "
        "«мои объявления», «сколько объявлений», «подними объявления», «обнови объявления», "
        "«удали объявление …», «отредактируй объявление …», «следи за ценой …», «мониторинг цен», "
        "«цена на <деталь>», «кто продаёт дешевле …», «лучшая цена», «отчёт по OLX», «статистика OLX», "
        "«автоответ олх», «выложи склад на олх», «подтверди телефон олх»",
    ),
    # Склад / инвентарь
    (
        "Склад",
        "«добавь деталь <название>, N шт по <цена>», «добавь на склад …», «спиши деталь …», "
        "«что на складе», «найди деталь …», «сколько стоит …», «остатки», «инвентаризация», "
        "«сколько деталей», «склад в таблицу», «товары», «изделия»",
    ),
    # Финансы
    (
        "Финансы",
        "«запиши продажу <деталь> за <цена>», «запиши расход <что> на <сумма>», «потратил …», "
        "«сколько заработал», «прибыль», «мои операции», «деньги за неделю», «деньги за месяц», "
        "«месячный отчёт», «итоги дня», «вечерний отчёт», «автономная бухгалтерия», "
        "«финансы в гугл таблицу»",
    ),
    # Новая Почта / логистика
    (
        "Новая Почта",
        "«создай ТТН <деталь>, <стоимость>, <получатель>, <телефон>, <город>, <отделение>» "
        "(с подтверждением), «отследи <ТТН>», «отправил <ТТН>», «клиенты», «мои клиенты», "
        "«посылки», «что в пути», «новая почта», «доставка»",
    ),
    # Единый инбокс
    (
        "Инбокс",
        "«инбокс» — показывает сохранённые непрочитанные сообщения (мгновенно, из кэша), "
        "«инбокс чаты» — только мессенджеры (TG, Direct, Messenger, Viber, Signal), "
        "«инбокс тг», «инбокс тг и инста», «инбокс вайбер», «инбокс олх», «инбокс телефон» — фильтры. "
        "Из мессенджеров — только ЛИЧНЫЕ переписки (без групп, каналов, ботов; Viber — только "
        "реальные контакты). Кнопка «🔄 Обновить» пересобирает из каналов; сбор новых сообщений "
        "происходит автоматически каждые 5 минут. Почта вынесена в отдельную команду: «почта» или "
        "«проверь почту». «озвучь инбокс», «найди во всех чатах <запрос>», «ответь на 3: текст», "
        "«присылай инбокс в HH:MM»",
    ),
    # Напоминания
    (
        "Напоминания",
        "«напомни [завтра/сегодня/послезавтра] в HH:MM <текст>», «напомни через 2 часа <текст>», "
        "«напоминай каждый день в 09:00 …», «напоминай каждую неделю …», «мои напоминания»",
    ),
    # Телефон / Android
    (
        "Телефон",
        "«мозг» (статус Phone Brain), «черновики», «подтверди 5», «центр телефона», "
        "«восстановление телефона», «инвентарь телефона», «банки телефона», «банковские уведомления», "
        "«маршруты», «калибровки», «журнал телефона», «задачи телефона», «лиды телефона», "
        "«непрочитанные уведомления телефона», «пришли коды подтверждения», «SMS», «смс-алерты»",
    ),
    # Фото / распознавание
    (
        "Фото",
        "«распознай деталь» (по фото), «что за деталь», «оцени деталь», «определи деталь», "
        "«сделай объявление из фото», «объявление по фото», «выложи по фото», «деталь по фото»",
    ),
    # Контент / посты
    (
        "Контент",
        "«запланируй пост в инстаграм на <дата> …», «пост в тикток на …», «опубликуй видео в тикток …», "
        "«расписание постов», «планировщик постов», «сторис»",
    ),
    # Мессенджеры / ответы клиентам
    (
        "Мессенджеры и ответы",
        "«ответь клиенту …», «быстрый ответ», «шаблоны ответов», «напиши в вайбер <имя>: текст», "
        "«напиши в сигнал <имя>: текст», «напиши в мессенджер <имя>: текст», «ответь в телегу …», "
        "«вайбер непрочитанные» / «вайбер сообщения» — непрочитанные Viber с телефона "
        "(авто-добавляются в инбокс; ответ — «ответь на N: текст» → подтвердить «да»), "
        "«автоответ олх», «автоответ покупателям», «личные черновики», «iMe», «сигнал», «viber»",
    ),
    # CRM / продажи / клиенты
    (
        "CRM и продажи",
        "«клиенты», «кто ждёт ответа», «ожидающие», «задачи», «запиши продажу …», «сделки», "
        "«воронка продаж», «статус заказа», «жизненный цикл», «фоллоу-ап», «шаблоны фоллоу-ап»",
    ),
    # Аналитика / дайджесты
    (
        "Дайджесты и аналитика",
        "«утренний брифинг», «вечерний отчёт», «недельный дайджест», «рыночный дайджест», "
        "«итоги недели», «аналитика», «тренды», «статистика аккаунтов», «сколько прибавил»",
    ),
    # Маркетплейсы / площадки
    (
        "Маркетплейсы",
        "«пром», «prom.ua», «бигль», «bigl», «розатка», «rozetka», «шафа», «shafa», "
        "«тикток», «tiktok», «фейсбук», «facebook», «мессенджер», «iZI», «RIA»",
    ),
    # Сервер / администрирование
    (
        "Сервер",
        "«статус сервера», «покажи логи», «логи бота», «сколько места на диске», «docker ps», "
        "«контейнеры», «бэкап», «сделай бэкап», «перезапусти бота», «перезапусти <сервис>», "
        "«/cmd <команда>» — прямой доступ к консоли (root, /opt/octopus)",
    ),
]

TG_COMMANDS: list[tuple[str, str]] = [
    ("/menu, /start", "главное меню"),
    ("/help", "справка по командам"),
    ("/llm_mode", "сменить режим LLM (auto — балансер, gemini — Gemini Web)"),
    ("/llm_status", "статус LLM-провайдеров"),
    ("/cmd", "выполнить команду на сервере (root, /opt/octopus)"),
    ("/skills", "полный список возможностей системы"),
    ("/stats, /status", "статистика и платформы"),
    ("/olx, /olx_sub, /olx_latest, /olx_analytics", "работа с OLX"),
    ("/google, /instagram, /accounts", "управление аккаунтами"),
    ("/coder, /code, /review, /fix", "ИИ-кодер"),
]


# ---------------------------------------------------------------------------
# Сборка справки
# ---------------------------------------------------------------------------


def _fmt_skills(cats: dict[str, list[tuple[str, str]]], per_cat: int = 0) -> str:
    lines = []
    for cat, items in cats.items():
        if not items:
            continue
        head = f"{cat} ({len(items)} скилов)"
        if per_cat:
            head += ", примеры:"
        lines.append(f"• {head}")
        if per_cat:
            for name, desc in items[:per_cat]:
                lines.append(f"   - {name}: {desc}")
    return "\n".join(lines)


def build_sections() -> dict[str, Any]:
    """Собрать все секции справки."""
    skills = _load_skills()
    adapters = _load_adapters()
    modules = _load_modules()
    run_scripts = _load_run_scripts()

    nl_lines = []
    for dom, cmds in NL_COMMANDS:
        nl_lines.append(f"• {dom}: {cmds}")

    ad_lines = []
    for cls, desc in adapters:
        ad_lines.append(f"• {cls}" + (f" — {desc}" if desc else ""))

    return {
        "built_at": time.time(),
        "skills_categories": {k: len(v) for k, v in skills.items()},
        "skills_total": sum(len(v) for v in skills.values()),
        "adapters": adapters,
        "modules": modules,
        "run_scripts": run_scripts,
        "tg_commands": TG_COMMANDS,
        "nl_commands": NL_COMMANDS,
    }


def _prompt_text(s: dict[str, Any]) -> str:
    """Компактная справка для промпта LLM — ТОЛЬКО NL-управление обычным языком."""
    lines = []

    lines.append("УПРАВЛЕНИЕ ОБЫЧНЫМ ЯЗЫКОМ (просто напиши боту фразу):")
    for dom, cmds in s["nl_commands"]:
        lines.append(f"  • {dom}: {cmds}")

    lines.append("")
    lines.append("ПЛАТФОРМЫ/АДАПТЕРЫ (интеграции):")
    ad = s.get("adapters") or []
    if ad:
        lines.append("  " + ", ".join(cls for cls, _ in ad[:24]))
    else:
        lines.append("  —")

    lines.append("")
    lines.append("МОДУЛИ ИНТЕГРАЦИЙ: " + ", ".join(s.get("modules") or ["—"]))

    lines.append("")
    lines.append(f"СКИЛЫ (Octopus, всего {s.get('skills_total', 0)}):")
    cats = s.get("skills_categories") or {}
    if cats:
        top = sorted(cats.items(), key=lambda x: -x[1])[:8]
        lines.append("  категории: " + ", ".join(f"{k} ({v})" for k, v in top))
    lines.append("  полный список — команда /skills")

    lines.append("")
    lines.append("ДОСТУП К СЕРВЕРУ: только через /cmd <команда> (root, /opt/octopus).")
    lines.append(
        "ПРАВИЛО: если пользователь спрашивает «что ты умеешь», «какие есть функции»,"
    )
    lines.append(
        "«как сделать X» — используй эту справку и предложи конкретную фразу управления"
    )
    lines.append(
        "обычным языком. НЕ показывай shell-команды без явного запроса через /cmd."
    )
    return "\n".join(lines)


def _full_text(s: dict[str, Any]) -> str:
    """Полная справка для /skills."""
    lines = []
    lines.append("🧠 AIOS — ВОЗМОЖНОСТИ СИСТЕМЫ")
    lines.append("=" * 40)
    lines.append("")

    lines.append("🗣 УПРАВЛЕНИЕ ОБЫЧНЫМ ЯЗЫКОМ:")
    for dom, cmds in s["nl_commands"]:
        lines.append(f"  • {dom}:\n      {cmds}")
    lines.append("")

    lines.append("📋 КОМАНДЫ TELEGRAM-БОТА:")
    lines.extend(f"  {c} — {d}" for c, d in s["tg_commands"])
    lines.append("")

    lines.append("🔌 ПЛАТФОРМЫ И АДАПТЕРЫ:")
    ad = s.get("adapters") or []
    if ad:
        for cls, desc in ad:
            lines.append(f"  • {cls}" + (f" — {desc}" if desc else ""))
    else:
        lines.append("  —")
    lines.append("")

    lines.append("🧩 МОДУЛИ ИНТЕГРАЦИЙ:")
    mods = s.get("modules") or []
    lines.append("  " + ", ".join(mods))
    lines.append("")

    lines.append(f"🎯 СКИЛЫ OCTOPUS (всего {s.get('skills_total', 0)}):")
    cats = s.get("skills_categories") or {}
    if cats:
        for k, v in sorted(cats.items(), key=lambda x: -x[1]):
            lines.append(f"  • {k}: {v} скилов")
    lines.append("  Полный каталог: skills/SKILLS_INDEX.md")
    lines.append("")

    lines.append("🚀 ТОЧКИ ВХОДА (run_*.py):")
    for name, desc in (s.get("run_scripts") or [])[:40]:
        lines.append(f"  • {name}" + (f" — {desc}" if desc else ""))
    lines.append("")

    lines.append("🖥 ДОСТУП К СЕРВЕРУ: /cmd <команда> (root, /opt/octopus).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Кэш + публичный API
# ---------------------------------------------------------------------------


def _load_cache() -> dict | None:
    try:
        if CACHE_FILE.exists():
            d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - d.get("built_at", 0) < CACHE_TTL:
                return d
    except Exception:
        pass
    return None


def rebuild_guide(force: bool = False) -> dict[str, Any]:
    """Пересобрать и сохранить справку."""
    cache = _load_cache()
    if cache and not force:
        return cache
    s = build_sections()
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"  [system_knowledge] cache write failed: {e}")
    return s


def get_system_guide(prompt_mode: bool = True) -> str:
    """Вернуть справку: prompt_mode=True — компактная (для LLM), иначе полная."""
    s = rebuild_guide()
    return _prompt_text(s) if prompt_mode else _full_text(s)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="System knowledge guide")
    ap.add_argument(
        "--rebuild", action="store_true", help="принудительно пересобрать кэш"
    )
    ap.add_argument("--show", action="store_true", help="показать справку")
    ap.add_argument("--full", action="store_true", help="полная справка (для /skills)")
    args = ap.parse_args()

    if args.rebuild:
        rebuild_guide(force=True)
        print("Справка пересобрана и сохранена в", CACHE_FILE)
    if args.show:
        print(get_system_guide(prompt_mode=not args.full))
