"""Клавиатуры Telegram-бота (выделено из run_telegram_bot.py)."""

from __future__ import annotations

MAIN_MENU_KEYBOARD = {
    # Решение владельца 2026-08-19: в боте одна кнопка — «Трейдинг».
    # Все команды (/quant, /olx, /ab, /scoreboard, …) остаются доступны текстом.
    "keyboard": [
        [{"text": "📈 Трейдинг"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


# Inline-главное меню: по решению владельца 2026-08-19 одна кнопка — «Трейдинг»
MAIN_MENU_INLINE = {
    "inline_keyboard": [
        [{"text": "📈 Трейдинг", "callback_data": "nav_trading"}],
    ]
}


# Быстрые действия OLX (v22.8): кнопки под сообщением раздела
OLX_ACTIONS_INLINE = {
    "inline_keyboard": [
        [
            {"text": "📊 Статистика", "callback_data": "olx_stats"},
            {"text": "🆕 Последние", "callback_data": "olx_latest"},
        ],
        [
            {"text": "📈 Аналитика цен", "callback_data": "olx_analytics"},
            {"text": "📋 Подписки", "callback_data": "olx_subs"},
        ],
        [{"text": "🏬 Склад", "callback_data": "nav_catalog"}],
    ]
}


CODER_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "📋 Статус"}, {"text": "📦 Бэклог"}],
        [{"text": "⚖️ Балансер"}, {"text": "📜 Git"}],
        [{"text": "🔍 Review Bot"}, {"text": "🔍 Review Coder"}],
        [{"text": "✨ Написать код"}, {"text": "🔧 Исправить"}],
        [{"text": "🚀 Push"}, {"text": "🔄 Перезапуск"}],
        [{"text": "◀️ Меню"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


OLX_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 OLX Стат"}, {"text": "📋 Подписки"}],
        [{"text": "🆕 Последние"}, {"text": "📈 Аналитика"}],
        [{"text": "◀️ Меню"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


ACCOUNTS_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "🌐 Google"}, {"text": "📸 Instagram"}],
        [{"text": "📘 Facebook"}, {"text": "🎵 TikTok"}],
        [{"text": "🛒 OLX"}, {"text": "◀️ Меню"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


PHONE_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "📲 Центр телефона"}, {"text": "🛠 Восстановление"}],
        [{"text": "📥 Лиды телефона"}, {"text": "📌 CRM задачи"}],
        [{"text": "🏦 Банки телефона"}, {"text": "📈 Тренды телефона"}],
        [{"text": "🔄 Синхронизации"}, {"text": "📋 Журнал телефона"}],
        [{"text": "🗄 Здоровье данных"}, {"text": "📦 Инвентарь"}],
        [{"text": "📤 Экспорт метрик"}, {"text": "🧩 Калибровки"}],
        [{"text": "🧪 Сценарии"}, {"text": "🚕 Маршруты"}],
        [{"text": "◀️ Меню"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


GOOGLE_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "✉️ Непрочитанные"}, {"text": "📥 Последние письма"}],
        [{"text": "🔍 Поиск письма"}, {"text": "📧 Отправить письмо"}],
        [{"text": "👤 Кто я"}, {"text": "📅 События"}],
        [{"text": "➕ Событие"}, {"text": "📄 Документ"}],
        [{"text": "🗂 Диск"}, {"text": "📷 Скрин почты"}],
        [{"text": "◀️ Аккаунты"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


INSTAGRAM_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "👤 Мой профиль"}, {"text": "📈 Подписчики"}],
        [{"text": "🖼 Мои посты"}, {"text": "📷 Скрин профиля"}],
        [{"text": "💬 Директ"}, {"text": "❤️ Лайкнуть"}],
        [{"text": "👤 Подписка"}, {"text": "◀️ Аккаунты"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


BOT_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Статус бота"}, {"text": "⏸️ Пауза"}],
        [{"text": "▶️ Старт"}, {"text": "🔄 Рестарт"}, {"text": "⏹️ Стоп"}],
        [{"text": "🌐 Gemini Web"}, {"text": "🔄 Балансер"}],
        [{"text": "◀️ Меню"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}


DANGEROUS_CALLBACKS = {"coder_git_push", "coder_restart", "bot_restart", "bot_stop"}

# Быстрые действия для Крипто-Заработка (5 бирж)
CRYPTO_ACTIONS_INLINE = {
    "inline_keyboard": [
        [
            {"text": "📊 График PnL", "callback_data": "crypto_chart"},
            {"text": "💼 Открытые позиции", "callback_data": "crypto_positions"},
        ],
        [
            {"text": "⚡ Арбитраж цен", "callback_data": "crypto_arb"},
            {"text": "🔄 Обновить сводку", "callback_data": "crypto_refresh"},
        ],
    ]
}
