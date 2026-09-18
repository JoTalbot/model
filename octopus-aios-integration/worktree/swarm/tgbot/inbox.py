"""Унифицированный инбокс (выделено из run_telegram_bot.py)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime

from swarm.tgbot.common import DATA_DIR, PROJECT_ROOT, _esc_tg, _run_account_control, _smart_model
from swarm.tgbot.state import (
    _CHANNELS,
    _last_inbox,
    _last_inbox_filters,
    _pending_confirm,
)

INBOX_SCHEDULE_FILE = DATA_DIR / "inbox_schedule.json"


INBOX_CACHE_FILE = DATA_DIR / "inbox_cache.json"


def _inbox_cache_load() -> list[dict]:
    """Сохранённые карточки инбокса (собраны фоновым сборщиком)."""
    try:
        d = json.loads(INBOX_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("items"), list):
            return d["items"]
    except Exception:
        pass
    return []


def _inbox_cache_save(items: list[dict]) -> None:
    try:
        INBOX_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        INBOX_CACHE_FILE.write_text(
            json.dumps(
                {"updated_at": datetime.now().strftime("%H:%M"), "items": items},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"  [INBOX-CACHE] save err: {e}")


def _inbox_refresh_now(filters: dict | None = None) -> list[dict]:
    """Полный сбор инбокса (дёргает адаптеры) + сохранение в кэш."""
    filters = dict(filters or {})
    items, _summary = _collect_inbox(filters)
    _inbox_cache_save(items)
    return items


def _is_service_preview(text: str) -> bool:
    """Служебные события не должны выглядеть как новые клиентские сообщения."""
    low = " ".join(str(text or "").casefold().split())
    return any(
        marker in low
        for marker in (
            "голосовий виклик завершився",
            "голосовой вызов завершился",
            "відеовиклик завершився",
            "видеовызов завершился",
            "started a call",
            "ended a call",
            "вызов завершен",
            "виклик завершено",
        )
    )


def _parse_inbox_filters(text: str) -> dict:
    """Парсинг фильтров инбокса: only_unread, channels.

    Поддерживает два стиля команд:
      * «только X» — классический: «инбокс только тг»
      * «инбокс X [и Y]» — новый: «инбокс чаты», «инбокс тг», «инбокс тг и инста»
    «чаты» = все мессенджеры (tg, ig, messenger, viber, signal).
    """
    t = " ".join((text or "").casefold().split())
    words = set(t.split())
    filters = {"unread_only": False, "channels": []}
    if any(
        w in t for w in ("только непрочитанное", "только непрочитанные", "непрочитанн")
    ):
        filters["unread_only"] = True

    chans: set[str] = set()

    # --- маркеры каналов (работают и без «только») ---
    if any(w in t for w in ("почт", "gmail", "гмаил")):
        chans.add("gmail")
    if (
        any(w in t for w in ("телеграм", "телега", "личк"))
        or "тг" in words
        or "tg" in words
    ):
        chans.add("tg")
    if (
        any(w in t for w in ("инстаграм", "инст", "direct", "директ"))
        or "ig" in words
        or "дм" in words
        or "dm" in words
    ):
        chans.add("ig")
    if (
        any(w in t for w in ("мессенджер", "messenger", "фейсбук", "facebook"))
        or "фб" in words
        or "fb" in words
    ):
        chans.add("messenger")
    if any(w in t for w in ("вайбер", "вибер", "viber")):
        chans.add("viber")
    if any(w in t for w in ("signal", "сигнал")):
        chans.add("signal")
    if any(w in t for w in ("телефон", "android", "андроид", "смс")):
        chans.add("android")
    if any(w in t for w in ("олх", "olx")):
        chans.add("olx")

    # «чаты» — все мессенджеры (без почты, телефона, OLX)
    if "чат" in t:
        chans.update(["tg", "ig", "messenger", "viber", "signal"])

    filters["channels"] = sorted(chans)
    return filters


def _collect_inbox(filters: dict | None = None) -> tuple[list[dict], str]:
    """Собрать пункты инбокса. Возвращает (items, summary)."""
    filters = filters or {}
    chans = filters.get("channels") or []
    unread_only = filters.get("unread_only", False)
    items: list[dict] = []
    summary_parts: list[str] = []

    def _want(ch: str) -> bool:
        return (not chans) or ch in chans

    # Почта (gmail) НЕ входит в инбокс — вынесена в отдельную команду «почта».
    # 1) Telegram — только личные переписки (без групп/каналов/супергрупп)
    if _want("tg"):
        try:
            tg = _run_account_control(["tg", "dialogs", "200"])
            if tg.get("status") == "ok" and tg.get("dialogs"):
                def _is_personal_tg(d):  # без ботов
                    return (d.get("type") or "user") == "user"
                personal_tg = [d for d in tg["dialogs"] if _is_personal_tg(d)]
                unread_d = [d for d in personal_tg if d.get("unread")]
                src = unread_d if unread_only else personal_tg
                for d in src[:20]:
                    items.append(
                        {
                            "channel": "tg",
                            "ref": d.get("name") or str(d.get("id")),
                            "title": d.get("name") or "?",
                            "preview": (d.get("last_msg") or "")[:80],
                            "unread": bool(d.get("unread")),
                            "date": "",
                        }
                    )
                if unread_d:
                    summary_parts.append(f"✈️ {len(unread_d)} личных чатов TG с новыми")
        except Exception:
            pass

    # 3) Instagram Direct
    if _want("ig"):
        try:
            ig = _run_account_control(["instagram", "dm_list", "6"])
            if ig.get("status") == "ok" and ig.get("threads"):
                meaningful = 0
                for d in ig["threads"][:5]:
                    _ig_name_low = (d.get("name") or "").lower()
                    if _ig_name_low.startswith(
                        ("вы и", "you and")
                    ):  # групповой чат Direct
                        continue
                    preview = (d.get("preview") or "")[:80]
                    service = _is_service_preview(preview)
                    if unread_only and service:
                        continue
                    items.append(
                        {
                            "channel": "ig",
                            "ref": d.get("name") or "?",
                            "title": d.get("name") or "?",
                            "preview": preview,
                            "unread": not service,
                            "service": service,
                            "date": "",
                        }
                    )
                    meaningful += int(not service)
                if meaningful:
                    summary_parts.append(f"📸 {meaningful} новых чатов IG Direct")
        except Exception:
            pass

    # 4) Messenger
    if _want("messenger"):
        try:
            ms = _run_account_control(["facebook", "messenger_list", "--limit", "6"])
            if ms.get("status") == "ok" and ms.get("chats"):
                meaningful = 0
                for c in ms["chats"][:5]:
                    preview = (c.get("preview") or "")[:80]
                    service = _is_service_preview(preview)
                    if unread_only and service:
                        continue
                    items.append(
                        {
                            "channel": "messenger",
                            "ref": c.get("name") or "?",
                            "title": c.get("name") or "?",
                            "preview": preview,
                            "unread": not service,
                            "service": service,
                            "date": "",
                        }
                    )
                    meaningful += int(not service)
                if meaningful:
                    summary_parts.append(f"💬 {meaningful} новых чатов Messenger")
        except Exception:
            pass

    # 5) Выбранные уведомления реального Android-телефона.
    #    (Viber-уведомления живут в этом же файле и помечаются каналом "viber")
    if _want("android") or _want("viber"):
        try:
            path = PROJECT_ROOT / "data" / "android_gateway" / "notifications.json"
            phone_events = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            )
            for event in reversed(phone_events[-30:]):
                if unread_only and event.get("read"):
                    continue
                title = str(event.get("title") or event.get("app") or "Телефон")
                app = str(event.get("app") or "Android")
                _t_title = title.lower()
                if (
                    "aios" in _t_title
                    or "выгодный лот" in _t_title
                    or "донор под разбор" in _t_title
                    or "брифинг" in _t_title
                    or "отчёт" in _t_title
                    or "черновик" in _t_title
                ):
                    continue  # служебные уведомления от самого AIOS — не в инбокс
                # Viber с телефона → канал "viber", ref = имя контакта (можно ответить)
                if app == "Viber":
                    items.append(
                        {
                            "channel": "viber",
                            "ref": title.strip() or "Viber",
                            "title": title.strip() or "Viber",
                            "preview": str(event.get("text") or "")[:120],
                            "unread": not bool(event.get("read")),
                            "date": str(event.get("collected_at") or "")[:19],
                            "source": "phone",
                        }
                    )
                    continue
                items.append(
                    {
                        "channel": "android",
                        "ref": str(event.get("id") or ""),
                        "title": f"{app}: {title}",
                        "preview": str(event.get("text") or "")[:120],
                        "unread": not bool(event.get("read")),
                        "date": str(event.get("collected_at") or "")[:19],
                    }
                )
            unread_phone = sum(1 for event in phone_events if not event.get("read"))
            if unread_phone:
                summary_parts.append(f"📲 {unread_phone} новых уведомлений телефона")
        except Exception:
            pass

    # 6) Viber Desktop — реальные контакты (OCR-фильтр в viber_control.chats).
    if _want("viber") and not unread_only:
        try:
            vb = _run_account_control(["viber", "chats"])
            if vb.get("status") == "ok" and vb.get("chats"):
                seen_viber = set()
                for c in vb["chats"][:12]:
                    name = str(c.get("name") or "").strip()
                    if not name or name.casefold() in seen_viber:
                        continue
                    seen_viber.add(name.casefold())
                    items.append(
                        {
                            "channel": "viber",
                            "ref": name,
                            "title": name,
                            "preview": "Viber: откройте пункт, чтобы прочитать последние сообщения",
                            "unread": True,  # OCR не даёт флаг — считаем новым
                            "date": "",
                        }
                    )
                if seen_viber:
                    summary_parts.append(f"💜 {len(seen_viber)} чатов Viber")
        except Exception:
            pass

    # 6) Signal Desktop — только по явному запросу («инбокс сигнал»),
    # т.к. OCR-распознавание имён ненадёжно.
    if (
        _want("signal")
        and not unread_only
        and "signal" in (filters.get("channels") or [])
    ):
        try:
            sig = _run_account_control(["signal", "chats"])
            if sig.get("status") == "ok" and sig.get("chats"):
                seen_signal = set()
                for c in sig["chats"][:12]:
                    name = str(c.get("name") or "").strip()
                    if not name or name.casefold() in seen_signal:
                        continue
                    seen_signal.add(name.casefold())
                    items.append(
                        {
                            "channel": "signal",
                            "ref": name,
                            "title": name,
                            "preview": "Signal: откройте пункт, чтобы прочитать последние сообщения",
                            "unread": True,  # OCR не даёт флаг — считаем новым
                            "date": "",
                        }
                    )
                if seen_signal:
                    summary_parts.append(f"🔒 {len(seen_signal)} чатов Signal")
        except Exception:
            pass

    # 7) OLX
    if _want("olx"):
        try:
            olx = _run_account_control(["olx", "profile"])
            if olx.get("status") == "ok" and olx.get("olx"):
                o = olx["olx"]
                items.append(
                    {
                        "channel": "olx",
                        "ref": o.get("name") or "olx",
                        "title": f"OLX: {o.get('name') or '?'}",
                        "preview": f"объявлений: {o.get('ads_count') or 0} · баланс: {o.get('balance') or 0} грн",
                        "unread": False,
                        "date": "",
                    }
                )
        except Exception:
            pass

    summary = ", ".join(summary_parts) if summary_parts else "нового нет"
    return items, summary


def _format_inbox(items: list[dict], filters: dict | None = None) -> str:
    """Красивые компактные карточки общего инбокса для Telegram."""
    from collections import Counter

    filters = filters or {}
    unread = sum(1 for item in items if item.get("unread"))
    by_channel = Counter(item.get("channel") for item in items)
    channel_summary = " · ".join(
        f"{_CHANNELS.get(channel, ('📄', channel))[0]} {count}"
        for channel, count in by_channel.items()
    )
    head = "📥 <b>ЕДИНЫЙ ИНБОКС</b>"
    if filters.get("channels"):
        labels = [_CHANNELS.get(c, ("", c))[1] for c in filters["channels"]]
        head += " · " + ", ".join(labels)
    subtitle = f"{len(items)} карточек"
    if unread:
        subtitle += f" · 🔴 {unread} новых"
    if channel_summary:
        subtitle += f"\n{channel_summary}"
    lines = [head, f"<i>{subtitle}</i>", "━━━━━━━━━━━━━━━━"]
    for index, item in enumerate(items[:12], 1):
        emoji, channel = _CHANNELS.get(
            item.get("channel"), ("📄", item.get("channel", ""))
        )
        badge = (
            "🔴 Новое"
            if item.get("unread")
            else ("⚪ Служебное" if item.get("service") else "◦ Просмотр")
        )
        title = _esc_tg(str(item.get("title") or "Без названия"))[:64]
        preview = _esc_tg(str(item.get("preview") or ""))[:115]
        lines.append(f"╭─ <code>{index:02d}</code> {emoji} <b>{channel}</b> · {badge}")
        lines.append(f"├ <b>{title}</b>")
        if preview:
            lines.append(f"├ <i>{preview}</i>")
        date = str(item.get("date") or "").strip()
        lines.append(
            f"╰ {'🕐 ' + _esc_tg(date) if date else 'Нажмите кнопку, чтобы открыть'}"
        )
    if len(items) > 12:
        lines.append(f"\n<i>Показаны первые 12 из {len(items)} карточек.</i>")
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append(
        "<i>Откройте карточку кнопкой ниже · «ответь на N: текст» · «сводка»</i>"
    )
    return "\n".join(lines)[:3900]


def _inbox_keyboard(items: list[dict], force: bool = False) -> dict | None:
    """Удобные кнопки карточек: открыть, обновить, сводка, отметить прочитанным.

    force=True — показать служебные кнопки (Обновить/Сводка) даже при пустом списке.
    """
    if not items and not force:
        return None
    rows = []
    button_row = []
    for index, item in enumerate(items[:8], 1):
        emoji, _ = _CHANNELS.get(item.get("channel"), ("📄", ""))
        label = f"{emoji} {index}"
        button_row.append({"text": label, "callback_data": f"inbox_read_{index}"})
        if len(button_row) == 4:
            rows.append(button_row)
            button_row = []
    if button_row:
        rows.append(button_row)
    rows.append(
        [
            {"text": "🔄 Обновить", "callback_data": "inbox_refresh"},
            {"text": "🧠 Сводка", "callback_data": "inbox_summary"},
        ]
    )
    rows.append([{"text": "✅ Отметить прочитанным", "callback_data": "inbox_readall"}])
    return {"inline_keyboard": rows}


def _inbox_summarize(items: list[dict]) -> str:
    """Умное резюме инбокса через LLM."""
    data_lines = []
    for i, it in enumerate(items, 1):
        _em, ch = _CHANNELS.get(it["channel"], ("", it["channel"]))
        data_lines.append(f"{i}. [{ch}] {it['title']} — {it['preview'][:100]}")
    prompt = (
        "Ты — ассистент, помогающий с единым инбоксом сообщений. "
        "Ниже нумерованный список новых пунктов из разных каналов (Telegram, Instagram DM, "
        "Messenger, Viber, Signal, телефон, OLX). Составь КРАТКОЕ резюме на русском (3-6 строк): что самое важное/срочное, "
        "кому стоит ответить, что проверить. Упомяни номера пунктов. "
        "Формат: начни с «🧠 Сводка:», потом маркированный список. Без воды.\n\n"
        + "\n".join(data_lines)
    )
    try:
        text = _llm_chat_direct(prompt)
        return text or "🧠 Сводка: нового ничего срочного."
    except Exception:
        return "🧠 Сводка: не удалось составить (LLM недоступен)."


def _llm_chat_direct(prompt: str) -> str:
    """Одиночный LLM-вызов (без истории), возвращает текст."""
    import urllib.request as _urllib

    _b = None
    try:
        from swarm.tgbot.support.llm_balancer import LLMBalancer as _LB

        _b = _LB()
    except Exception:
        _b = None
    if _b is not None:
        try:
            r = _b.chat(
                [{"role": "user", "content": prompt}],
                model=_smart_model(),
                system="Ты краткий ассистент инбокса. Отвечай на русском.",
                max_tokens=400,
                temperature=0.3,
                task_type="chat",
            )
            if r:
                return r
        except Exception:
            pass
    try:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if key:
            payload = json.dumps(
                {
                    "model": "mistralai/mistral-small-3.2-24b-instruct",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 400,
                    "temperature": 0.3,
                }
            ).encode()
            req = _urllib.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + key,
                },
            )
            with _urllib.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception:
        pass
    return ""


def _inbox_reply(api, chat_id: int, item: dict, body: str) -> None:
    """Ответить на пункт инбокса в нужный канал."""
    ch = item.get("channel")
    ref = item.get("ref")
    if not body:
        api.send_message(chat_id, "❌ Укажите текст ответа: «ответь на N: текст»")
        return
    if ch == "gmail":
        # ответить на письмо (email id)
        if ref.isdigit():
            _pending_confirm[chat_id] = {
                "kind": "gmail_reply",
                "data": {"msg_id": ref, "idx": 1, "text": body},
            }
            api.send_message(
                chat_id,
                f"📧 Ответ на письмо «{_esc_tg(item.get('title'))[:50]}»:\n«{body[:150]}»\n\nОтправить? «да» / «нет»",
            )
        else:
            api.send_message(chat_id, "❌ Не удалось определить письмо для ответа.")
    elif ch == "tg":
        _pending_confirm[chat_id] = {
            "kind": "tg_send",
            "data": {"ref": ref, "text": body},
        }
        api.send_message(
            chat_id,
            f"✈️ Ответ в Telegram <b>{_esc_tg(ref)}</b>:\n«{body[:150]}»\n\nОтправить? «да» / «нет»",
        )
    elif ch == "ig":
        _pending_confirm[chat_id] = {
            "kind": "dm_send",
            "data": {"thread": ref, "text": body},
        }
        api.send_message(
            chat_id,
            f"📸 Ответ в Instagram Direct <b>{_esc_tg(ref)}</b>:\n«{body[:150]}»\n\nОтправить? «да» / «нет»",
        )
    elif ch == "messenger":
        _pending_confirm[chat_id] = {
            "kind": "messenger_send",
            "data": {"chat": ref, "text": body},
        }
        api.send_message(
            chat_id,
            f"💬 Ответ в Messenger <b>{_esc_tg(ref)}</b>:\n«{body[:150]}»\n\nОтправить? «да» / «нет»",
        )
    elif ch == "viber":
        _pending_confirm[chat_id] = {
            "kind": "viber_send",
            "data": {"chat": ref, "text": body},
        }
        api.send_message(
            chat_id,
            f"💜 Ответ в Viber <b>{_esc_tg(ref)}</b>:\n«{body[:150]}»\n\nОтправить? «да» / «нет»",
        )
    elif ch == "signal":
        _pending_confirm[chat_id] = {
            "kind": "signal_send",
            "data": {"chat": ref, "text": body},
        }
        api.send_message(
            chat_id,
            f"🔒 Ответ в Signal <b>{_esc_tg(ref)}</b>:\n«{body[:150]}»\n\nОтправить? «да» / «нет»",
        )
    else:
        api.send_message(chat_id, "❌ Для этого пункта ответ не поддерживается.")


def _inbox_voice(api, chat_id: int, items: list[dict]) -> None:
    """Озвучить инбокс через gTTS и отправить голосовое."""
    try:
        from gtts import gTTS
    except ImportError:
        api.send_message(chat_id, "🎙 Озвучка недоступна (gTTS не установлен).")
        return
    lines = ["Инбокс. "]
    for i, it in enumerate(items[:12], 1):
        lines.append(f"{i}. {it['title']}. {it['preview'][:60]}")
    text = " ".join(lines)[:1500]
    try:
        tts = gTTS(text=text, lang="ru")
        path = f"/tmp/aios_inbox_voice_{int(time.time())}.mp3"
        tts.save(path)
        api.send_voice(chat_id, path, caption="🎙 Инбокс голосом")
        print(f"  [INBOX] voice sent ({len(text)} chars)")
    except Exception as e:
        print(f"  [INBOX] voice err: {e}")
        api.send_message(chat_id, "🎙 Не удалось озвучить: " + str(e)[:150])


def _inbox_search(api, chat_id: int, q: str) -> None:
    """Поиск по всем каналам."""
    found = []
    # почта (полнотекстовый IMAP)
    try:
        g = _run_account_control(["google", "gmail_search", q, "5"])
        if g.get("status") == "ok" and g.get("emails"):
            for e in g["emails"][:5]:
                found.append(
                    f"✉️ <b>{_esc_tg(e.get('subject', '?'))}</b>\n   {_esc_tg((e.get('from') or '')[:50])}"
                )
    except Exception:
        pass
    # Telegram (топ диалогов)
    try:
        tg = _run_account_control(["tg", "dialogs", "50"])
        if tg.get("status") == "ok" and tg.get("dialogs"):
            for d in tg["dialogs"][:6]:
                name = d.get("name") or ""
                last = d.get("last_msg") or ""
                if q.lower() in last.lower() or q.lower() in name.lower():
                    found.append(f"✈️ <b>{_esc_tg(name)}</b>: {_esc_tg(last[:80])}")
    except Exception:
        pass
    # Instagram DM (топ чатов)
    try:
        ig = _run_account_control(["instagram", "dm_list", "6"])
        if ig.get("status") == "ok" and ig.get("threads"):
            for d in ig["threads"][:5]:
                if (
                    q.lower() in (d.get("preview") or "").lower()
                    or q.lower() in (d.get("name") or "").lower()
                ):
                    found.append(
                        f"📸 <b>{_esc_tg(d.get('name'))}</b>: {_esc_tg((d.get('preview') or '')[:80])}"
                    )
    except Exception:
        pass
    # Viber: поиск по видимым чатам без открытия переписки и без пометки прочитанным.
    try:
        vb = _run_account_control(["viber", "chats"])
        if vb.get("status") == "ok":
            for c in (vb.get("chats") or [])[:20]:
                name = str(c.get("name") or "")
                if q.lower() in name.lower():
                    found.append(f"💜 <b>{_esc_tg(name)}</b>: Viber чат")
    except Exception:
        pass
    # Signal: поиск по видимым чатам без открытия переписки.
    try:
        sig = _run_account_control(["signal", "chats"])
        if sig.get("status") == "ok":
            for c in (sig.get("chats") or [])[:20]:
                name = str(c.get("name") or "")
                if q.lower() in name.lower():
                    found.append(f"🔒 <b>{_esc_tg(name)}</b>: Signal чат")
    except Exception:
        pass
    if not found:
        api.send_message(
            chat_id, f"🔍 По запросу «{q}» ничего не найдено (или каналы недоступны)."
        )
    else:
        api.send_message(
            chat_id, f"🔍 <b>Найдено по «{q}»:</b>\n\n" + "\n".join(found)[:3900]
        )


def _inbox_mark_read(api, chat_id: int) -> None:
    """Отметить прочитанным (почта через IMAP, TG через userbot)."""
    done = []
    # почта: пометить все \Seen
    try:
        import run_account_control as _rac

        pw = _rac.app_password()
        if pw:
            import imaplib

            M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            M.login(_rac.GOOGLE_EMAIL, pw)
            M.select("INBOX")
            _typ, data = M.search(None, "UNSEEN")
            ids = data[0].split()
            if ids:
                M.store(b",".join(ids), "+FLAGS", "\\Seen")
            M.logout()
            done.append(f"✉️ почта: {len(ids)} прочитано")
    except Exception as e:
        print(f"  [INBOX] mark gmail err: {e}")
    # Telegram
    try:
        r = _run_account_control(["tg", "read", "Saved Messages", "--limit", "1"])
        if r.get("status") == "ok":
            done.append("✈️ Telegram: диалоги открыты (пометка частичная)")
    except Exception:
        pass
    # Пометить локально собранные Android-уведомления прочитанными.
    try:
        import subprocess as _sp

        result = _sp.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "run_android_notification_collector.py"),
                "mark-read",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        payload = json.loads((result.stdout or "{}").strip())
        if payload.get("status") == "ok":
            done.append(f"📲 Телефон: {payload.get('marked', 0)} уведомлений отмечено")
    except Exception:
        pass
    # Остальные desktop/Direct каналы намеренно не открываем пачкой: это либо
    # меняет состояние чатов, либо API не даёт безопасной bulk-операции.
    done.append("📸 Direct и 💬 Messenger: массовая пометка недоступна безопасно")
    done.append("💜 Viber: массовая отметка не выполнялась")
    done.append("🔒 Signal: массовая отметка не выполнялась")
    _last_inbox.pop(chat_id, None)
    _last_inbox_filters.pop(chat_id, None)
    api.send_message(
        chat_id,
        "✅ <b>Инбокс обработан</b>\n━━━━━━━━━━━━━━━━\n"
        + "\n".join(f"• {line}" for line in done)
        + "\n━━━━━━━━━━━━━━━━\n<i>Откройте «инбокс» для обновлённых карточек.</i>",
    )


def _inbox_schedule_cmd(api, chat_id: int, text: str) -> None:
    """Управление расписанием инбокса."""
    t = text.lower()
    try:
        sched = (
            json.loads(INBOX_SCHEDULE_FILE.read_text(encoding="utf-8"))
            if INBOX_SCHEDULE_FILE.exists()
            else {}
        )
    except Exception:
        sched = {}
    cur = sched.get(str(chat_id), [])
    if "отключ" in t or "выключ" in t or "убери" in t:
        sched[str(chat_id)] = []
        INBOX_SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
        INBOX_SCHEDULE_FILE.write_text(
            json.dumps(sched, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        api.send_message(chat_id, "⏰ Расписание инбокса отключено.")
        return
    m_time = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t)
    if not m_time:
        api.send_message(
            chat_id,
            "⏰ Формат: «присылай инбокс в 09:00» или «присылай инбокс вечером в 21:00»",
        )
        return
    hh, mm = int(m_time.group(1)), int(m_time.group(2))
    when = "утром" if hh < 12 else ("днём" if hh < 17 else "вечером")
    entry = {"time": f"{hh:02d}:{mm:02d}", "label": when}
    cur = [e for e in cur if e.get("time") != entry["time"]]
    cur.append(entry)
    sched[str(chat_id)] = sorted(cur, key=lambda e: e["time"])
    INBOX_SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INBOX_SCHEDULE_FILE.write_text(
        json.dumps(sched, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    api.send_message(
        chat_id,
        f"⏰ Инбокс буду присылать {when} в {entry['time']}. "
        f"«отключи инбокс» — убрать расписание.",
    )


def _run_due_inbox(token: str) -> int:
    """Отправить инбокс по расписанию (раз в минуту)."""
    if not INBOX_SCHEDULE_FILE.exists():
        return 0
    try:
        sched = json.loads(INBOX_SCHEDULE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0
    now_hhmm = datetime.now().strftime("%H:%M")
    sent = 0
    for chat_s, entries in sched.items():
        for e in entries:
            if e.get("time") == now_hhmm:
                chat_id = int(chat_s)
                # не дублируем: файл last_sent
                last_file = PROJECT_ROOT / "data" / "inbox_last_sent.json"
                try:
                    last = json.loads(last_file.read_text(encoding="utf-8"))
                except Exception:
                    last = {}
                if last.get(str(chat_id)) == now_hhmm:
                    continue
                last[str(chat_id)] = now_hhmm
                last_file.write_text(json.dumps(last), encoding="utf-8")
                items, _ = _collect_inbox({})
                if items:
                    _last_inbox[chat_id] = items
                    try:
                        import urllib.request as _urllib

                        payload = json.dumps(
                            {
                                "chat_id": chat_id,
                                "text": _format_inbox(items),
                                "parse_mode": "HTML",
                            }
                        ).encode()
                        req = _urllib.Request(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            data=payload,
                            headers={"Content-Type": "application/json"},
                        )
                        with _urllib.urlopen(req, timeout=90):
                            pass
                        sent += 1
                        print(f"  [INBOX-SCHED] sent to {chat_id}")
                    except Exception as ex:
                        print(f"  [INBOX-SCHED] err: {ex}")
    return sent
