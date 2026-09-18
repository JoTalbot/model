"""Живая сводка AIOS — единый стиль форматирования для Telegram-бота.

Собирает актуальные показатели по всем направлениям (склад, OLX, конкуренты,
фриланс, система) и форматирует их в едином стиле: секции, иконки, аккуратные отступы.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

_TRIGGERS = (
    "сводка",
    "дашборд",
    "итоги",
    "обзор",
    "все показатели",
    "статус системы",
    "📊 сводка",
    "общая сводка",
    "что по деньгам",
    "что по бизнесу",
)

# Триггеры фриланс-сводки (кнопка «💼 Фриланс»)
_FREELANCE_TRIGGERS = (
    "фриланс",
    "ставки фриланса",
    "заказы фриланса",
    "💼 фриланс",
    "сколько заявок",
    "что по фрилансу",
)


def _load(name: str, default):
    p = DATA / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt(n) -> str:
    try:
        return f"{float(n):,.0f}".replace(",", " ")
    except Exception:
        return str(n)


def warehouse_block() -> str:
    items = _load("inventory.json", [])
    if not items:
        return "📦 Склад: нет данных"
    total_qty = sum(int(it.get("qty", 0)) for it in items)
    total_val = sum(float(it.get("price", 0)) * int(it.get("qty", 0)) for it in items)
    pub = _load("olx_published.json", [])
    lines = [
        "🏬 <b>Склад</b>",
        f"  📦 {len(items)} позиций · {total_qty} ед.",
        f"  💰 Стоимость: <b>{_fmt(total_val)} грн</b>",
        f"  🛒 На OLX: {len(pub) if isinstance(pub, list) else '?'}",
    ]
    return "\n".join(lines)


def competitors_block() -> str:
    mon = _load("competitor_monitor.json", {})
    if not mon or not mon.get("items"):
        return "🆚 Конкуренты: нет данных (запусти мониторинг)"
    below = sum(1 for i in mon["items"] if i["position"] == "below_market")
    above = sum(1 for i in mon["items"] if i["position"] == "above_market")
    no_comp = sum(1 for i in mon["items"] if i["competitors"] == 0)
    with_comp = mon.get("positions_with_competitors", 0)
    return (
        "🆚 <b>Конкуренты (OLX)</b>\n"
        f"  🔎 Позиций с конкурентами: {with_comp}\n"
        f"  ⬇️ Ниже рынка: {below} · ⬆️ Выше: {above} · 🕳 Без конкуренции: {no_comp}"
    )


def freelance_block() -> str:
    tasks = _load("freelance_tasks.json", [])
    if not tasks:
        return "💼 Фриланс: нет данных"
    ready = [t for t in tasks if t.get("status") == "PROPOSAL_READY"]
    notified = [t for t in ready if t.get("approval_notified")]
    total_usd = sum(float(t.get("budget_usd", 0)) for t in ready)
    return (
        "💼 <b>Фриланс</b>\n"
        f"  📝 Готово предложений: {len(ready)} (≈ ${_fmt(total_usd)})\n"
        f"  📨 Уведомлено в TG: {len(notified)} (ждут твоего approve)"
    )


def system_block() -> str:
    loadavg = "—"
    mem = "—"
    try:
        la = os.getloadavg()
        loadavg = f"{la[0]:.1f} / {la[1]:.1f} / {la[2]:.1f}"
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                k, _, v = line.partition(":")
                meminfo[k] = int(v.strip().split()[0]) // 1024  # MB
        total = meminfo.get("MemTotal", 0)
        avail = meminfo.get("MemAvailable", 0)
        pct = int((total - avail) / total * 100) if total else 0
        mem = f"{pct}% занято ({avail} МБ свободно)"
    except Exception:
        pass
    return f"🖥 <b>Система</b>\n  ⚙️ Load: {loadavg}\n  🧠 RAM: {mem}"


def render_dashboard() -> str:
    blocks = [
        warehouse_block(),
        competitors_block(),
        freelance_block(),
        system_block(),
    ]
    return "\n\n".join(blocks)


def _handle_dashboard_intent(api, chat_id: int, text: str) -> bool:
    t = " ".join(str(text or "").casefold().split())
    if not any(phrase in t for phrase in _TRIGGERS):
        return False
    try:
        txt = "📊 <b>AIOS — Сводка</b>\n\n" + render_dashboard()
        api.send_message(chat_id, txt)
    except Exception:
        api.send_message(
            chat_id, render_dashboard().replace("<b>", "").replace("</b>", "")
        )
    return True


def _handle_freelance_summary_intent(api, chat_id: int, text: str) -> bool:
    """«фриланс», «список фриланса» — детальный список заказов и проектов фриланса с ID."""
    t = " ".join(str(text or "").casefold().split())
    if not any(phrase in t for phrase in _FREELANCE_TRIGGERS) and not any(
        p in t for p in ("список", "заказы", "проекты")
    ):
        return False

    api.send_message(
        chat_id, "💼 <b>Запрашиваю активные заказы и список проектов фриланса...</b>"
    )
    import json
    import urllib.request

    tasks = _load("freelance_tasks.json", [])

    live_fh_projects = []
    from pathlib import Path

    env_file = Path(os.environ.get("OCTOPUS_ENV_FILE", "/etc/octopus/octopus.env"))
    token = ""
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("FREELANCEHUNT_API_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")

    if token:
        try:
            url = "https://api.freelancehunt.com/v2/projects?page[number]=1"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                live_fh_projects = data.get("data", [])
        except Exception:
            pass

    lines = ["💼 <b>Свободные заказы фриланса (с ID для выбора):</b>", ""]

    if live_fh_projects:
        lines.append("🔥 <b>Свежие открытые заказы на Freelancehunt:</b>")
        for p in live_fh_projects[:5]:
            p_id = p.get("id")
            p_attr = p.get("attributes", {})
            title = p_attr.get("name", "")
            b_data = p_attr.get("budget") or {}
            b_amount = b_data.get("amount", 700) if isinstance(b_data, dict) else 700
            b_curr = (
                b_data.get("currency", "UAH") if isinstance(b_data, dict) else "UAH"
            )
            lines.append(f"• <b>№ {p_id}</b>: {title}")
            lines.append(f"  Бюджет: <b>{b_amount} {b_curr}</b>")
            lines.append(f"  Ссылка: https://freelancehunt.com/project/{p_id}.html")
            lines.append(f"  👉 Ставка: <code>отправь ставку {p_id} {b_amount}</code>")
            lines.append("")

    ready_tasks = [
        x
        for x in tasks
        if isinstance(x, dict)
        and x.get("status") in ("PROPOSAL_READY", "BID_SUBMITTED")
    ]
    if ready_tasks:
        lines.append("📋 <b>Задачи AIOS в работе:</b>")
        for x in ready_tasks[:5]:
            t_id = x.get("id")
            title = x.get("title", "")
            budget = x.get("budget_usd", 0.0)
            source = x.get("source", "")
            lines.append(f"• <b>ID: {t_id}</b> ({source})")
            lines.append(f"  <i>{title}</i>")
            lines.append(f"  Бюджет: <b>${budget} USD</b>")
            lines.append(
                f"  Инвойс: <code>инвойс фриланс {t_id}</code> | Подтвердить: <code>подтверди фриланс {t_id}</code>"
            )
            lines.append("")

    api.send_message(chat_id, "\n".join(lines)[:4000])
    return True
