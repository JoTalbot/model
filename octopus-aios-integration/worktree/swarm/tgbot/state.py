"""Общее изменяемое состояние Telegram-бота (разделяется монолитом и tg_bot/*).

ВНИМАНИЕ: эти объекты импортируются по ссылке — мутации видимы везде.
"""

from __future__ import annotations

_pending_confirm: dict[int, dict] = {}


_last_inbox: dict[int, list[dict]] = {}


_last_inbox_filters: dict[int, dict] = {}


_CHANNELS = {
    "gmail": ("✉️", "Почта"),
    "tg": ("✈️", "Telegram"),
    "ig": ("📸", "Instagram DM"),
    "messenger": ("💬", "Messenger"),
    "viber": ("💜", "Viber"),
    "signal": ("🔒", "Signal"),
    "android": ("📲", "Телефон"),
    "olx": ("🛒", "OLX"),
}


_last_photo: dict[int, str] = {}


_photo_pending: dict[int, bool] = {}


_last_gen_ad: dict[int, str] = {}


_last_video: dict[int, str] = {}


_last_gmail_ids: dict[int, list[str]] = {}


_phone_route_drafts: dict[int, dict] = {}


_phone_brain_state: dict = {"ok": None, "checked": 0.0}


_last_phone_leads: dict[int, list[dict]] = {}


_last_phone_crm_tasks: dict[int, list[dict]] = {}


_last_bank_tasks: dict[int, list[dict]] = {}


_pending_actions: dict[int, str] = {}


_pending_confirmations: dict[int, str] = {}

# === NEW: инвентарь по фото (фича v22.1) ===

# Альбомы Telegram (media_group_id -> {chat_id, photos:[paths], caption, ts, processed})
_photo_albums: dict[str, dict] = {}

# Черновики товаров на складе по фото: draft_id -> {name, qty, price, category, photos:[], condition, compatible, notes, provider, chat_id, ts}
_inventory_drafts: dict[str, dict] = {}

# Ожидание редактирования полей черновика: chat_id -> {draft_id, field} где field = price|name|qty|category
_pending_inventory_edits: dict[int, dict] = {}

# Временное хранилище для добавления фото к черновику: chat_id -> draft_id ожидающий дополнительного фото
_pending_add_photo: dict[int, str] = {}
