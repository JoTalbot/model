"""Unified Inbox router (выделено из run_telegram_bot.py).

Приоритетный роутер инбокса до Instagram Direct и прочих платформ:
расписание, «отметить прочитанным», ответы по номеру карточки, озвучка,
поиск по всем каналам, общая сводка сообщений.
"""

from __future__ import annotations

import re

from swarm.tgbot.common import _esc_tg
from swarm.tgbot.inbox import (
    _collect_inbox,
    _format_inbox,
    _inbox_cache_load,
    _inbox_keyboard,
    _inbox_mark_read,
    _inbox_refresh_now,
    _inbox_reply,
    _inbox_schedule_cmd,
    _inbox_search,
    _inbox_summarize,
    _inbox_voice,
    _parse_inbox_filters,
)
from swarm.tgbot.state import _last_inbox, _last_inbox_filters


def _send_unified_inbox(
    api,
    chat_id: int,
    text: str = "",
    filters: dict | None = None,
    refresh: bool = False,
) -> None:
    """Показать инбокс.

    refresh=True — собрать из каналов (дёргает адаптеры) и обновить кэш;
    refresh=False — показать сохранённые сообщения (не дёргая адаптеры).
    Показываются только непрочитанные карточки. Почта — отдельная команда «почта».
    """
    filters = dict(filters or _parse_inbox_filters(text))
    lower = " ".join((text or "").casefold().split())

    # почта вынесена в отдельную команду «почта»
    if filters.get("channels") == ["gmail"] or lower in (
        "инбокс почта",
        "инбокс гмаил",
        "инбокс gmail",
        "инбокс только почта",
    ):
        api.send_message(
            chat_id,
            "📬 <b>Почта вынесена в отдельную команду.</b>\n\n"
            "Напишите «почта» или «проверь почту» — покажу письма отдельно.",
        )
        return

    if refresh:
        api.send_message(chat_id, "⏳ <b>Обновляю инбокс…</b> проверяю каналы")
        items = _inbox_refresh_now(filters)
        if not items:
            api.send_message(
                chat_id,
                "📭 <b>Инбокс пуст</b>\nНовых карточек по каналам нет.",
                reply_markup=_inbox_keyboard([], force=True),
            )
            return
    else:
        items = _inbox_cache_load()
        if not items:
            api.send_message(
                chat_id,
                "📥 <b>Инбокс</b>\n\nСохранённых сообщений пока нет.\n"
                "Нажмите «🔄 Обновить», чтобы проверить каналы.",
                reply_markup=_inbox_keyboard([], force=True),
            )
            return

    # показываем только непрочитанные
    unread_items = [it for it in items if it.get("unread")]
    if not unread_items:
        api.send_message(
            chat_id,
            "✅ <b>Инбокс</b>\nНовых непрочитанных сообщений нет.",
            reply_markup=_inbox_keyboard([], force=True),
        )
        return
    _last_inbox[chat_id] = unread_items
    _last_inbox_filters[chat_id] = filters
    if any(word in lower for word in ("сводк", "резюме", "кратко", "умн")):
        api.send_message(chat_id, "🧠 Составляю сводку по карточкам…")
        api.send_message(chat_id, _inbox_summarize(unread_items)[:3900])
    else:
        api.send_message(
            chat_id,
            _format_inbox(unread_items, filters),
            reply_markup=_inbox_keyboard(unread_items),
        )


def _handle_unified_inbox_intent(api, chat_id: int, text: str) -> bool:
    """Приоритетный роутер инбокса до Instagram Direct и прочих платформ."""
    t = " ".join((text or "").casefold().split())
    if not t:
        return False

    # Расписание должно перехватываться раньше общего слова «инбокс».
    if re.match(
        r"^(присылай|пришли|включи|отключи|выключи|убери)\s+инбокс", t
    ) or re.match(r"^(включи|отключи)\s+расписание\s+инбокса", t):
        _inbox_schedule_cmd(api, chat_id, text)
        return True

    # Пользовательский вариант «отметить все непрочитанные сообщения в инбоксе
    # прочитанными» раньше ошибочно попадал в обработчик Instagram Direct.
    mark_read = (
        (
            any(stem in t for stem in ("отмет", "пометь", "отмеч"))
            and "прочитан" in t
            and any(word in t for word in ("инбокс", "сообщен", "все", "всё"))
        )
        or "всё прочитано" in t
        or "все прочитаны" in t
    )
    if mark_read:
        _inbox_mark_read(api, chat_id)
        return True

    m_reply = re.match(
        r"^(ответь|reply|отв[её]ть)\s+(?:на\s+)?#?(\d+)\s*:?\s*(.+)$",
        text,
        re.IGNORECASE,
    )
    if m_reply:
        if chat_id not in _last_inbox:
            api.send_message(
                chat_id, "ℹ️ Сначала откройте «инбокс», затем выберите номер карточки."
            )
            return True
        idx = int(m_reply.group(2))
        body = m_reply.group(3).strip()
        items = _last_inbox.get(chat_id, [])
        if 1 <= idx <= len(items):
            _inbox_reply(api, chat_id, items[idx - 1], body)
        else:
            api.send_message(chat_id, f"❌ Нет карточки №{idx} в последнем инбоксе.")
        return True

    if any(
        phrase in t
        for phrase in (
            "озвучь инбокс",
            "озвучь всё",
            "голосом инбокс",
            "прочитай инбокс вслух",
        )
    ):
        api.send_message(chat_id, "⏳ Собираю карточки для озвучки…")
        items, _summary = _collect_inbox({})
        if not items:
            api.send_message(chat_id, "📭 Инбокс пуст.")
        else:
            _last_inbox[chat_id] = items
            _last_inbox_filters[chat_id] = {}
            _inbox_voice(api, chat_id, items)
        return True

    m_search = re.match(
        r"^(найди во всех|ищи везде|найди везде|поиск по всем)\s*(?:чатах|сообщениях|каналах)?\s*:?\s*(.+)$",
        text,
        re.IGNORECASE,
    )
    if m_search:
        query = m_search.group(2).strip()
        if query:
            api.send_message(
                chat_id, f"🔍 Ищу «{_esc_tg(query)}» по подключённым каналам…"
            )
            _inbox_search(api, chat_id, query)
        else:
            api.send_message(chat_id, "🔍 Формат: «найди во всех чатах &lt;запрос&gt;»")
        return True

    inbox_terms = (
        "инбокс",
        "inbox",
        "все сообщения",
        "всё в одном",
        "сводка сообщений",
        "где что новое",
        "проверь всё",
    )
    if any(term in t for term in inbox_terms):
        _send_unified_inbox(api, chat_id, text, refresh=True)
        return True
    return False
