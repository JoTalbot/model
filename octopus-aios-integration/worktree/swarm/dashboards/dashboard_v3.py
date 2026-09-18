# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
#!/usr/bin/env python3
"""
AIOS Dashboard v3 — сводка всех аккаунтов (web, nicegui).
Порт 8090, только localhost. Показывает: подписчики IG/TikTok, OLX, посылки,
почта, напоминания, шаблоны, подписки на цены.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from nicegui import ui

ROOT = Path(__file__).resolve().parent


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _analytics() -> dict:
    return _read_json(ROOT / "data" / "analytics_state.json")


def _reminders() -> list:
    try:
        return json.loads((ROOT / "data" / "reminders.json").read_text(encoding="utf-8"))
    except Exception:
        return []


def _np_parcels() -> dict:
    return _read_json(ROOT / "data" / "np_alerts_state.json")


def _price_subs() -> dict:
    return _read_json(ROOT / "data" / "olx_price_subs.json")


def _templates() -> dict:
    return _read_json(ROOT / "data" / "templates.json")


def _inventory() -> list:
    try:
        return json.loads((ROOT / "data" / "inventory.json").read_text(encoding="utf-8"))
    except Exception:
        return []


def _finance() -> list:
    try:
        return json.loads((ROOT / "data" / "finance.json").read_text(encoding="utf-8"))
    except Exception:
        return []



def _sales_lifecycle() -> list[dict]:
    try:
        data = json.loads((ROOT / "data" / "sales_lifecycle.json").read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _sales_tasks() -> list[dict]:
    try:
        data = json.loads((ROOT / "data" / "sales_tasks.json").read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _sales_summary(sales: list[dict], tasks: list[dict]) -> dict:
    """CRM-метрики без персональных данных клиентов."""
    active_statuses = {"awaiting_shipment", "ttn_created", "in_transit", "returning"}
    active = [sale for sale in sales if sale.get("status") in active_statuses]
    return {
        "total": len(sales),
        "active": len(active),
        "awaiting": sum(1 for sale in sales if sale.get("status") in ("awaiting_shipment", "ttn_created")),
        "in_transit": sum(1 for sale in sales if sale.get("status") == "in_transit"),
        "delivered": sum(1 for sale in sales if sale.get("status") == "delivered"),
        "returned": sum(1 for sale in sales if sale.get("status") in ("returned", "return_received", "returning")),
        "open_tasks": sum(1 for task in tasks if task.get("status") == "open"),
        "pipeline_amount": round(sum(_number(sale.get("amount")) for sale in active), 2),
    }

def _android_device() -> dict:
    return _read_json(ROOT / "data" / "android_gateway" / "health.json")


def _android_lead_summary() -> dict:
    """Metadata-only count of potential messenger contacts for the dashboard."""
    try:
        from aios_core.android_leads import AndroidLeadQueue
        return AndroidLeadQueue(ROOT).summary()
    except Exception:
        return {"status": "error", "pending": 0, "by_source": {}}


def _android_audit_summary() -> dict:
    try:
        from aios_core.android_audit import PhoneActionAudit
        return PhoneActionAudit(ROOT).summary()
    except Exception:
        return {"status": "error", "count": 0, "last": None}


def _phone_operations() -> dict:
    """Safe phone operations summary without messages, screens or coordinates."""
    try:
        from aios_core.phone_control_center import PhoneControlCenter
        return PhoneControlCenter(ROOT).snapshot()
    except Exception:
        return {"status": "error", "issues": ["unavailable"]}


# Тяжёлый phone-снапшот (HTTP к companion + adb-подпроцессы) НЕ должен
# блокировать event loop NiceGUI: считаем в фоновом потоке, страница читает кэш.
_HEAVY_CACHE: dict = {"ts": 0.0, "data": None}


def _heavy_snapshot() -> dict:
    return _HEAVY_CACHE["data"] or {"status": "warming", "issues": []}


def _warm_loop() -> None:
    while True:
        try:
            _HEAVY_CACHE["data"] = _phone_operations()
        except Exception:
            _HEAVY_CACHE["data"] = {"status": "error", "issues": ["unavailable"]}
        _HEAVY_CACHE["ts"] = time.monotonic()
        time.sleep(60)


threading.Thread(target=_warm_loop, daemon=True, name="dash-heavy-cache").start()


def _customer_crm() -> dict:
    try:
        from aios_core.crm import CRMStore
        return CRMStore(ROOT).snapshot(limit=20)
    except Exception:
        return {"status": "error", "count": 0, "customers": [], "tags": {}}


def _olx_stats() -> dict:
    try:
        conn = sqlite3.connect(str(ROOT / "data" / "olx_http.sqlite"))
        total = conn.execute("SELECT COUNT(*) FROM ads WHERE active = 1").fetchone()[0]
        min_p = conn.execute("SELECT MIN(price_value) FROM ads WHERE price_value > 0 AND active = 1").fetchone()[0]
        conn.close()
        return {"total": total, "min_price": min_p}
    except Exception:
        return {"total": 0, "min_price": None}


def _llm_keys() -> dict:
    """Статус LLM-провайдеров и ключей (без раскрытия значений)."""
    out = {"providers": {}, "captcha_balance": None, "error": ""}
    try:
        from aios_core.llm_balancer import LLMBalancer
        b = LLMBalancer()
        for name, prov in b.providers.items():
            keys = getattr(prov, "keys", [])
            out["providers"][name] = {
                "total": len(keys),
                "healthy": sum(1 for k in keys if not getattr(k, "in_cooldown", lambda: False)()),
            }
    except Exception as exc:  # noqa: BLE001
        out["error"] = "balancer: " + str(exc)
    try:
        state = json.loads((ROOT / "data" / "captcha_balance_state.json").read_text(encoding="utf-8"))
        out["captcha_balance"] = state.get("balance")
    except Exception:
        pass
    return out


def _llm_usage() -> dict:
    """Агрегированная статистика из usage.jsonl (за сутки)."""
    out = {"calls": 0, "tokens": 0, "by_provider": {}}
    log = ROOT / "data" / "llm" / "usage.jsonl"
    if not log.exists():
        return out
    import time as _t
    day_ago = _t.time() - 86400
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if (rec.get("ts") or 0) < day_ago:
            continue
        out["calls"] += 1
        tok = int(rec.get("total_tokens") or 0)
        out["tokens"] += tok
        prov = str(rec.get("provider") or "?")
        pr = out["by_provider"].setdefault(prov, {"calls": 0, "tokens": 0})
        pr["calls"] += 1
        pr["tokens"] += tok
    return out


def build() -> None:
    ui.page_title("AIOS Dashboard")
    with ui.header().classes("bg-blue-900"):
        ui.label("AIOS — сводка аккаунтов").classes("text-2xl font-bold")
        ui.label(datetime.now().strftime("%d.%m.%Y %H:%M")).classes("text-sm")

    # Аналитика (подписчики)
    hist = _analytics()
    with ui.card().classes("w-full"):
        ui.label("📊 Аналитика").classes("text-lg font-bold")
        if hist:
            last_date = sorted(hist.keys())[-1]
            last = hist[last_date]
            with ui.row():
                ui.label(f"Instagram подписчики: {last.get('instagram_followers', '—')}").classes("text-base")
                ui.label(f"TikTok подписчики: {last.get('tiktok_followers', '—')}").classes("text-base")
                ui.label(f"TikTok лайки: {last.get('tiktok_likes', '—')}").classes("text-base")
        else:
            ui.label("Нет данных (снапшоты собираются ежедневно)")

    # OLX
    olx = _olx_stats()
    with ui.card().classes("w-full"):
        ui.label("🛒 OLX").classes("text-lg font-bold")
        ui.label(f"Активных объявлений в БД: {olx['total']} · мин цена: {olx['min_price'] or '—'} грн")
        subs = _price_subs()
        if subs:
            ui.label("Подписки на цены:").classes("text-sm font-bold")
            for chat, entries in subs.items():
                for e in entries:
                    ui.label(f"• {e.get('query')} — мин {e.get('last_min') or '?'} грн").classes("text-sm")

    # Продажи / CRM (не выводим ФИО и телефоны на общий экран)
    sales = _sales_lifecycle()
    sale_tasks = _sales_tasks()
    crm = _sales_summary(sales, sale_tasks)
    status_label = {
        "awaiting_shipment": "Ожидает отправки", "ttn_created": "ТТН создана",
        "in_transit": "В пути", "delivered": "Доставлено", "returning": "Возврат в пути",
        "returned": "Возврат получен", "return_received": "Возвращено на склад",
    }
    status_color = {
        "awaiting_shipment": "text-amber-700", "ttn_created": "text-amber-700",
        "in_transit": "text-blue-700", "delivered": "text-green-700",
        "returning": "text-orange-700", "returned": "text-red-700", "return_received": "text-gray-700",
    }
    with ui.card().classes("w-full border-l-4 border-indigo-500"):
        ui.label("💼 Продажи и CRM").classes("text-lg font-bold")
        with ui.row().classes("w-full gap-4"):
            for label, value, color in (
                ("Активные сделки", crm["active"], "text-indigo-700"),
                ("Ждут отправки", crm["awaiting"], "text-amber-700"),
                ("В пути", crm["in_transit"], "text-blue-700"),
                ("Доставлено", crm["delivered"], "text-green-700"),
                ("Открытые задачи", crm["open_tasks"], "text-red-700"),
            ):
                with ui.card().classes("min-w-32 bg-slate-50"):
                    ui.label(label).classes("text-xs text-gray-500")
                    ui.label(str(value)).classes(f"text-2xl font-bold {color}")
        ui.label(f"Сумма активных сделок: {crm['pipeline_amount']:.0f} грн · возвратов: {crm['returned']}").classes("text-sm")
        if sales:
            ui.label("Последние сделки").classes("text-sm font-bold mt-2")
            for sale in sorted(sales, key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)[:8]:
                status = str(sale.get("status") or "unknown")
                item = str(sale.get("item") or "Товар")[:80]
                ttn = str(sale.get("ttn") or "—")
                amount = _number(sale.get("amount"))
                task_note = " · задача открыта" if any(t.get("sale_id") == sale.get("id") and t.get("status") == "open" for t in sale_tasks) else ""
                ui.label(f"• {status_label.get(status, status)} · {item} · ТТН {ttn} · {amount:.0f} грн{task_note}").classes(
                    f"text-sm {status_color.get(status, 'text-gray-700')}")
        else:
            ui.label("Сделок с ТТН пока нет").classes("text-sm text-gray-500")

    # Карточки клиентов CRM — только отображаемые псевдонимы и маски телефонов
    crm_customers = _customer_crm()
    with ui.card().classes("w-full border-l-4 border-violet-500"):
        ui.label("👥 Клиенты CRM").classes("text-lg font-bold")
        if crm_customers.get("customers"):
            tag_summary = " · ".join(f"{tag}: {count}" for tag, count in (crm_customers.get("tags") or {}).items())
            if tag_summary:
                ui.label(tag_summary).classes("text-xs text-gray-500")
            for customer in crm_customers["customers"][:10]:
                tags = " · ".join(customer.get("tags") or []) or "без тега"
                channels = ", ".join(customer.get("channels") or []) or "—"
                ui.label(
                    f"• {customer.get('display_name')} {customer.get('phone_masked') or ''} · "
                    f"{customer.get('sales_count', 0)} сделок · {customer.get('lifetime_amount', 0):.0f} грн · "
                    f"{tags} · {channels}").classes("text-sm")
        else:
            ui.label("Карточки появятся после синхронизации сделок с ТТН").classes("text-sm text-gray-500")

    # Реальный Android-адаптер
    android = _android_device()
    with ui.card().classes("w-full border-l-4 border-emerald-500"):
        ui.label("📱 Android Device Adapter").classes("text-lg font-bold")
        if android:
            state = "✅ подключён" if android.get("connected") else "⚠️ офлайн"
            ui.label(f"{state} · {android.get('name') or android.get('model') or 'Android'} · Android {android.get('android') or '—'}").classes("text-sm")
            if android.get("connected"):
                ui.label(f"Заряд: {android.get('battery', '—')}% · экран: {android.get('screen', '—')} · приложений: {android.get('packages', '—')}").classes("text-sm")
            companion = android.get("companion") or {}
            if companion:
                ui.label(f"Companion: {'✅ активен' if companion.get('connected') else '⚠️ недоступен'} · "
                         f"уведомления: {'да' if (companion.get('permissions') or {}).get('notification_listener') else 'нет'} · "
                         f"геолокация: {'да' if (companion.get('permissions') or {}).get('location') else 'нет'}").classes("text-sm")
        else:
            ui.label("Телефон ещё не зарегистрирован").classes("text-sm text-gray-500")
        leads = _android_lead_summary()
        pending_leads = int(leads.get("pending") or 0)
        lead_sources = " · ".join(f"{source}: {count}" for source, count in (leads.get("by_source") or {}).items())
        crm_followups = int(leads.get("crm_open") or 0)
        crm_attention = int(leads.get("crm_attention") or 0)
        crm_overdue = int(leads.get("crm_overdue") or 0)
        ui.label(
            f"Потенциальные лиды телефона: {pending_leads} · CRM follow-up: {crm_followups}"
            f" · внимание: {crm_attention} · просрочены: {crm_overdue}"
            + (f" · {lead_sources}" if lead_sources else "")
        ).classes("text-sm text-amber-700" if (pending_leads or crm_followups) else "text-sm text-gray-500")
        audit = _android_audit_summary()
        last_audit = audit.get("last") or {}
        if audit.get("count"):
            ui.label(
                f"Безопасный журнал телефона: {audit.get('count')} событий · "
                f"последнее: {last_audit.get('action', '—')} · {str(last_audit.get('at') or '')[:19]}"
            ).classes("text-xs text-gray-500")

    # Сводный безопасный центр управления телефоном.
    phone_ops = _heavy_snapshot()
    with ui.card().classes("w-full border-l-4 border-cyan-600"):
        ui.label("🛠 Центр управления телефоном").classes("text-lg font-bold")
        state = "✅ стабильно" if phone_ops.get("status") == "ok" else "⚠️ требуется внимание"
        device_ops = phone_ops.get("device") or {}
        sync_ops = phone_ops.get("sync") or {}
        jobs_ops = phone_ops.get("jobs") or {}
        inv_ops = phone_ops.get("inventory") or {}
        leads_ops = phone_ops.get("leads") or {}
        bank_ops = phone_ops.get("bank_tasks") or {}
        template_ops = phone_ops.get("templates") or {}
        ui.label(f"{state} · ADB: {'✅' if device_ops.get('connected') else '⚠️'} · Companion: {'✅' if device_ops.get('companion') else '⚠️'} · восстановление: {(phone_ops.get('recovery') or {}).get('action', '—')}").classes("text-sm")
        ui.label(f"Android {inv_ops.get('android') or '—'} · SDK {inv_ops.get('sdk') or '—'} · синхронизации: {sync_ops.get('fresh', 0)}/{sync_ops.get('total', 0)} · jobs: {jobs_ops.get('active', 0)}/{jobs_ops.get('total', 0)}").classes("text-sm")
        ui.label(f"Лиды: {leads_ops.get('pending', 0)} · CRM follow-up: {leads_ops.get('crm_open', 0)} · банковские задачи: {bank_ops.get('pending', 0)} · шаблоны: {template_ops.get('count', 0)}").classes("text-sm")
        ui.label(f"Данные: {(phone_ops.get('state_health') or {}).get('status', '—')} · WireGuard: {'✅' if (phone_ops.get('state_health') or {}).get('wireguard_active') else '⚠️'} · backup: {(phone_ops.get('state_health') or {}).get('backup_age_hours', '—')} ч").classes("text-xs text-gray-500")

    # Посылки Новой Пошты
    parcels = _np_parcels()
    with ui.card().classes("w-full"):
        ui.label("📦 Новая Пошта — посылки").classes("text-lg font-bold")
        if parcels:
            for ttn, info in parcels.items():
                ui.label(f"• {ttn}: {info.get('status', '—')}").classes("text-sm")
        else:
            ui.label("Нет посылок в отслеживании")

    # Напоминания
    rem = _reminders()
    with ui.card().classes("w-full"):
        ui.label("⏰ Напоминания").classes("text-lg font-bold")
        if rem:
            for r in rem[:10]:
                ui.label(f"• {r.get('at', '')[:16]}: {r.get('text', '')}").classes("text-sm")
        else:
            ui.label("Нет активных напоминаний")

    # Шаблоны
    tpl = _templates()
    with ui.card().classes("w-full"):
        ui.label("📝 Шаблоны ответов").classes("text-lg font-bold")
        if tpl:
            for k, v in list(tpl.items())[:10]:
                ui.label(f"• <b>{k}</b>: {v[:60]}").classes("text-sm").props("contenteditable=false")
        else:
            ui.label("Шаблонов пока нет")

    # Склад
    inv = _inventory()
    with ui.card().classes("w-full"):
        ui.label("📦 Склад").classes("text-lg font-bold")
        if inv:
            total_qty = sum(_number(x.get("qty")) for x in inv)
            total_reserved = sum(_number(x.get("reserved_qty")) for x in inv)
            total_available = max(0, total_qty - total_reserved)
            total_val = sum(max(0, _number(x.get("qty")) - _number(x.get("reserved_qty"))) * _number(x.get("price")) for x in inv)
            ui.label(f"Позиций: {len(inv)} · физически: {total_qty:.0f} шт · свободно: {total_available:.0f} шт · резерв: {total_reserved:.0f} шт").classes("text-sm")
            ui.label(f"Свободные запасы: {total_val:.0f} грн").classes("text-sm")
            for x in inv[:12]:
                qty = _number(x.get("qty")); reserved = _number(x.get("reserved_qty")); available = max(0, qty - reserved)
                mark = "✅" if available > 0 else ("⏳" if reserved else "❌")
                reserve_note = f" · резерв {reserved:.0f}" if reserved else ""
                ui.label(f"{mark} {x.get('name', '')} — свободно {available:.0f} из {qty:.0f} шт{reserve_note} · {x.get('price', 0)} грн").classes("text-sm")
        else:
            ui.label("Склад пуст")

    # Финансы
    fin = _finance()
    with ui.card().classes("w-full"):
        ui.label("💰 Финансы").classes("text-lg font-bold")
        if fin:
            sales = sum(x["amount"] for x in fin if x.get("kind") == "sale")
            exp = sum(x["amount"] for x in fin if x.get("kind") == "expense")
            ui.label(f"Продажи: {sales} · Расходы: {exp} · Прибыль: {sales - exp} грн").classes("text-sm")
            for x in fin[-6:][::-1]:
                em = "🟢" if x.get("kind") == "sale" else "🔴"
                ui.label(f"{em} {x.get('date', '')[:16]} — {x.get('desc', '')} — {x.get('amount')} грн").classes("text-sm")
        else:
            ui.label("Нет операций")

    # CRM публикуется через защищённый nginx-префикс /crm/.
    # финансы: 30 дней + график по дням
    try:
        fin = json.loads((ROOT / "data" / "finance.json").read_text(encoding="utf-8"))
        from datetime import timedelta as _td
        days = {}
        for x in fin if isinstance(fin, list) else []:
            d = str(x.get("date") or "")[:10]
            if not d:
                continue
            cur = days.setdefault(d, {"sale": 0.0, "expense": 0.0})
            cur[x.get("kind") or "expense"] += float(x.get("amount") or 0)
        keys = sorted(days.keys())[-14:]
        sales30 = sum(v["sale"] for v in days.values())
        exp30 = sum(v["expense"] for v in days.values())
        with ui.card().classes("w-full"):
            ui.label(f"💰 Финансы 30д: продажи {sales30:.0f} · расходы {exp30:.0f} · "
                     f"прибыль {sales30 - exp30:.0f} грн").classes("text-lg font-bold")
            if keys:
                ui.echart({
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": ["Продажи", "Расходы"]},
                    "xAxis": {"type": "category", "data": [k[5:] for k in keys]},
                    "yAxis": {"type": "value"},
                    "series": [
                        {"name": "Продажи", "type": "bar",
                         "data": [round(days[k]["sale"]) for k in keys]},
                        {"name": "Расходы", "type": "bar",
                         "data": [round(days[k]["expense"]) for k in keys]},
                    ],
                }).classes("w-full").style("height: 220px")
    except Exception:
        pass

    # Бэктест ML/RL стратегий
    try:
        bt_file = ROOT / "data" / "quant" / "backtest_results.json"
        if bt_file.exists():
            bt = json.loads(bt_file.read_text(encoding="utf-8"))
            with ui.card().classes("w-full border-l-4 border-emerald-500"):
                ui.label("📈 Бэктест стратегий").classes("text-lg font-bold")
                for sym, res in list(bt.items())[:6]:
                    if not isinstance(res, dict):
                        continue
                    ml = res.get("ml_50pct", {})
                    bh = res.get("buy_hold", {})
                    if isinstance(ml, dict) and "total_return_pct" in ml:
                        ui.label(f"{sym}: ML {ml.get('total_return_pct',0):+.2f}% | Sharpe {ml.get('sharpe',0)} | BuyHold {bh.get('total_return_pct',0):+.2f}%").classes("text-xs")
    except Exception:
        pass

    # RL-модель результат (best)
    try:
        rl_res = ROOT / "data" / "quant" / "backtest_summary.json"
        if rl_res.exists():
            rl = json.loads(rl_res.read_text(encoding="utf-8"))
            with ui.card().classes("w-full border-l-4 border-violet-500"):
                ui.label("🤖 RL-модель (валидация)").classes("text-lg font-bold")
                ui.label(f"Активов: {rl.get('assets', 0)}").classes("text-sm")
                ui.label("Топ-3 по ML-доходности:").classes("text-sm font-bold mt-1")
                for r in rl.get("results", [])[:3]:
                    ui.label(f"  {r['symbol']}: ML {r.get('ml_pct',0):+.2f}% | Sharpe {r.get('ml_sharpe',0)}").classes("text-xs")
    except Exception:
        pass

    # фотокаталог склада
    try:
        inv = json.loads((ROOT / "data" / "inventory.json").read_text(encoding="utf-8"))
        with_photos = [i for i in inv if isinstance(i, dict) and i.get("photo")
                       and Path(str(i["photo"])).exists()]
        if with_photos:
            with ui.card().classes("w-full"):
                ui.label("📦 Склад — фотокаталог").classes("text-lg font-bold")
                with ui.row().classes("flex-wrap items-start"):
                    for i in with_photos:
                        with ui.card().style("width: 230px"):
                            ui.image(str(i["photo"])).style("width: 100%; border-radius: 8px")
                            ui.label(str(i.get("name") or "")).classes("text-sm font-bold")
                            ui.label(f"{int(i.get('price') or 0)} грн · {int(i.get('qty') or 0)} шт").classes("text-xs")
    except Exception:
        pass

    # ML/RL модели и сигналы
    try:
        from aios_core.quant_trading_engine import get_ai_signal_summary
        ai = get_ai_signal_summary()
        ml = ai.get("ml", {})
        rl = ai.get("rl", {})
        with ui.card().classes("w-full border-l-4 border-violet-500"):
            ui.label("🤖 ML/RL Модели и Сигналы").classes("text-lg font-bold")
            with ui.row().classes("w-full gap-4"):
                with ui.card().classes("min-w-40 bg-slate-50"):
                    ui.label("ML (CatBoost)").classes("text-xs text-gray-500")
                    ui.label(f"Активов: {ml.get('total', 0)}").classes("text-xl font-bold")
                    ui.label(f"Бычьих: {ml.get('bullish_strong', 0)} · Медвежьих: {ml.get('bearish_strong', 0)}").classes("text-xs")
                    top = ml.get("top_momentum", [])
                    if top:
                        ui.label("Топ: " + ", ".join(top)).classes("text-xs")
                with ui.card().classes("min-w-40 bg-slate-50"):
                    ui.label("RL (PPO)").classes("text-xs text-gray-500")
                    ui.label(f"Активов: {rl.get('total', 0)}").classes("text-xl font-bold")
                    longs = rl.get("long", [])
                    halves = rl.get("half", [])
                    ui.label(f"LONG: {', '.join(longs) if longs else '—'}").classes("text-xs")
                    ui.label(f"HALF: {', '.join(halves[:6]) if halves else '—'}{'…' if len(halves)>6 else ''}").classes("text-xs")
            # статус моделей на диске
            models_dir = ROOT / "data" / "quant" / "models"
            if models_dir.exists():
                files = sorted(models_dir.glob("*"))
                if files:
                    ui.label("Модели на диске:").classes("text-sm font-bold mt-2")
                    for f in files:
                        sz = f.stat().st_size
                        ui.label(f"• {f.name} — {sz//1024} КБ").classes("text-xs text-gray-600")
    except Exception as e:
        pass



    # LLM-расход за сутки
    try:
        usage = _llm_usage()
        if usage.get("calls"):
            with ui.card().classes("w-full border-l-4 border-cyan-500"):
                ui.label("📈 LLM-расход (24ч)").classes("text-lg font-bold")
                with ui.row().classes("w-full gap-4"):
                    with ui.card().classes("min-w-36 bg-slate-50"):
                        ui.label("Вызовов").classes("text-xs text-gray-500")
                        ui.label(f"{usage['calls']:,}").classes("text-xl font-bold")
                    with ui.card().classes("min-w-36 bg-slate-50"):
                        ui.label("Токенов").classes("text-xs text-gray-500")
                        ui.label(f"{usage['tokens']:,}").classes("text-xl font-bold")
                    for prov, info in sorted(usage["by_provider"].items())[:5]:
                        with ui.card().classes("min-w-32 bg-slate-50"):
                            ui.label(prov).classes("text-xs text-gray-500")
                            ui.label(f"{info['tokens']:,}").classes("text-lg font-bold")
                            ui.label(f"{info['calls']} вызовов").classes("text-xs")
    except Exception:
        pass

    # LLM-провайдеры и ключи
    try:
        llm = _llm_keys()
        with ui.card().classes("w-full border-l-4 border-emerald-500"):
            ui.label("🔑 LLM-провайдеры").classes("text-lg font-bold")
            if llm.get("error"):
                ui.label("⚠️ " + llm["error"]).classes("text-sm text-red-600")
            if llm["providers"]:
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    for name, info in sorted(llm["providers"].items()):
                        with ui.card().classes("min-w-36 bg-slate-50"):
                            ui.label(name).classes("text-xs text-gray-500")
                            ui.label(f"{info['healthy']}/{info['total']}").classes("text-xl font-bold")
                            ui.label("ключей здорово").classes("text-xs")
            else:
                ui.label("Нет зарегистрированных провайдеров").classes("text-sm")
            bal = llm.get("captcha_balance")
            if bal is not None:
                color = "text-green-700" if bal >= 5 else "text-red-700"
                ui.label(f"2captcha баланс: <b>${bal:.2f}</b>").classes("text-sm " + color)
            # Лимиты groq (снапшот автопилота)
            try:
                lim = json.loads((ROOT / "data" / "llm" / "groq_limits.json").read_text(encoding="utf-8"))
                if lim.get("avg_remaining") is not None:
                    ui.label(f"Groq лимиты: в среднем <b>{lim['avg_remaining']:.0f}</b> RPM осталось "
                             f"({len(lim.get('keys', []))} ключей, проверено "
                             f"{datetime.fromtimestamp(lim['checked_at']).strftime('%H:%M')})").classes("text-sm")
            except Exception:
                pass
    except Exception:
        pass

    # Префикс /crm обеспечивает nginx (strip + auth); приложение работает без root_path,
    # а его статика и ws проксируются nginx-локациями /_nicegui/ и /_nicegui_ws/.
    ui.run(host="127.0.0.1", port=8090, reload=False, show=False)


if __name__ == "__main__":
    build()
