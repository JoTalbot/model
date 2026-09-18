"""
Gemini Web LLM Adapter — ответы через gemini.google.com в реальном браузере
===========================================================================
Альтернативный LLM-адаптер. **Нигде не используется автоматически** — только там,
где вызывается явно:
  * в чате Telegram-бота — команда `/llm_mode gemini` (см. run_telegram_bot.py);
  * из любого скрипта — `gemini_web_ask(prompt)`.

Как работает:
  1. Подключается к уже запущенному Chrome с личным Google-профилем
     (aios-chrome-vnc, CDP :9222, профиль `data/chrome_twin/default`,
     где залогинен Google-аккаунт).
  2. Открывает вкладку gemini.google.com/app → «Временный чат» (аналог
     инкогнито: ответы не сохраняются в историю аккаунта).
  3. Вставляет контекст + запрос, нажимает Enter, ждёт завершения генерации.
  4. Извлекает текст ответа модели и закрывает вкладку.

Безопасность / ограничения:
  * Никаких токенов и ключей — используется только живая сессия Google в профиле.
  * Запросы сериализуются глобальным замком (один общий Chrome, чтобы вкладки
    не мешали друг другу).
  * Требует живой Chrome на :9222 (`systemctl status aios-chrome-vnc`).
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

try:
    from playwright.async_api import async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    HAS_PLAYWRIGHT = False
    async_playwright = None

GEMINI_URL = "https://gemini.google.com/app"

try:
    from .system_knowledge import get_system_guide as _get_system_guide

    HAS_GUIDE = True
except Exception:
    _get_system_guide = None
    HAS_GUIDE = False

_CDP_DEFAULT = "http://127.0.0.1:9222"

# Файл режимов LLM: chat_id -> "auto" | "gemini"
_MODES_FILE = Path(__file__).resolve().parents[1] / "data" / "llm_modes.json"

_lock = threading.Lock()

# --- JS: вытащить ходы из разметки Gemini -------------------------------
_EXTRACT_JS = """
() => {
  const out = [];
  for (const n of document.querySelectorAll("message-content")) {
    let role = n.getAttribute("data-turn-role") || n.getAttribute("data-role") || "";
    if (!role) {
      const cls = n.className || "";
      if (/model|response|assistant/i.test(cls)) role = "model";
      else if (/user|request|query/i.test(cls)) role = "user";
    }
    const md = n.querySelector(".markdown");
    const text = md ? md.innerText : n.innerText;
    out.push({role: role, text: text || ""});
  }
  return out;
}
"""


# ---------------------------------------------------------------------------
# Режим LLM для чата (auto | gemini)
# ---------------------------------------------------------------------------


def _load_modes() -> dict[str, str]:
    try:
        if _MODES_FILE.exists():
            raw = json.loads(_MODES_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): str(v) for k, v in raw.items()}
    except Exception:
        pass
    return {}


def _save_modes(data: dict[str, str]) -> None:
    try:
        _MODES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _MODES_FILE.with_name(_MODES_FILE.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_MODES_FILE)
    except Exception as e:
        print(f"  [gemini_web] cannot save modes: {e}")


def get_llm_mode(chat_id: Any) -> str:
    """Текущий режим LLM для чата: 'auto' (балансер) или 'gemini' (Web)."""
    return _load_modes().get(str(chat_id), "auto")


def set_llm_mode(chat_id: Any, mode: str) -> None:
    """Установить режим LLM для чата ('gemini' — браузерный Gemini Web, иначе 'auto')."""
    data = _load_modes()
    data[str(chat_id)] = "gemini" if mode == "gemini" else "auto"
    _save_modes(data)


# ---------------------------------------------------------------------------
# Сборка единого промпта (контекст + запрос) для отправки в веб-форму
# ---------------------------------------------------------------------------

# Команды Telegram-бота, которые может использовать пользователь (для справки модели)
TG_COMMANDS_HELP = (
    "Команды Telegram-бота (пишутся в чат с «/»):\n"
    "/menu или /start — главное меню\n"
    "/help — список команд\n"
    "/llm_mode — посмотреть/сменить режим LLM (auto — балансер, gemini — Gemini Web)\n"
    "/llm_status — статус LLM-провайдеров\n"
    "/stats — статистика\n"
    "/status — платформы\n"
    "/olx, /olx_sub <запрос>, /olx_latest <запрос>, /olx_analytics <запрос> — OLX\n"
    "/google — Google-аккаунт (почта, календарь, диск)\n"
    "/instagram — Instagram (профиль, посты, директ)\n"
    "/accounts — управление аккаунтами\n"
    "/coder, /code, /review, /fix — ИИ-кодер\n\n"
    "Плюс обычные фразы: «проверь почту», «мой инстаграм», «календарь», «диск», "
    "«найди деталь», «склад», «напомни …», «сколько заработал» и т.п."
)


def build_gemini_prompt(
    system: str, messages: list[dict], max_turns: int = 10, max_chars: int = 12000
) -> str:
    """Собрать один текстовый промпт: системная инструкция + последние ходы.

    Gemini Web получает одну строку, поэтому роли размечаются текстом.
    messages — список {'role': 'user'|'assistant', 'content': ...}
    (может включать системный элемент — он игнорируется).
    """
    parts: list[str] = []
    if system:
        parts.append("=== СИСТЕМНАЯ ИНСТРУКЦИЯ (ты — Лиза) ===\n" + system)

    history = [
        m
        for m in (messages or [])
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and m.get("content")
    ]
    recent = history[-max_turns * 2 :]
    if recent:
        lines = []
        for m in recent:
            who = "Костя (пользователь)" if m.get("role") == "user" else "Лиза (ты)"
            lines.append(f"{who}: {m['content']}")
        parts.append("=== КОНТЕКСТ ДИАЛОГА (последние ходы) ===\n" + "\n".join(lines))

    try:
        _guide = _get_system_guide(prompt_mode=True) if HAS_GUIDE else TG_COMMANDS_HELP
    except Exception:
        _guide = TG_COMMANDS_HELP
    parts.append(
        "=== ВОЗМОЖНОСТИ СИСТЕМЫ (справка для подсказок пользователю) ===\n"
        + _guide
        + "\n\nВАЖНО: если пользователь спрашивает «что ты умеешь», «какие команды я могу "
        "использовать», «какие есть функции», «как сделать X» — ОБЯЗАТЕЛЬНО используй эту "
        "справку: перечисли КОНКРЕТНЫЕ возможности системы по доменам (OLX, склад, финансы, "
        "Новая Почта, инбокс, телефон, Instagram, Google, дайджесты и т.д.) с примерами фраз. "
        "Не отвечай общими словами («помогать с задачами», «писать код») без конкретики. "
        "НЕ выполняй и НЕ показывай shell-команды сервера без явного запроса через /cmd."
    )

    parts.append(
        "=== ПРАВИЛА ИСПОЛЬЗОВАНИЯ SHELL-ДОСТУПА ===\n"
        "У тебя есть доступ к серверу через теги <cmd>команда</cmd> — но использовать его "
        "МОЖНО ТОЛЬКО когда пользователь явно просит что-то сделать на сервере "
        "(например: «покажи логи», «перезапусти сервис», «сколько места на диске», "
        "«проверь статус»). НИКОГДА не отправляй <cmd> для примеров, объяснений или "
        "плейсхолдеров (типа <cmd>ls ...</cmd>). Если не уверен — не отправляй <cmd> вообще, "
        "просто ответь текстом. Не выдумывай команды с многоточием «...»."
    )

    parts.append(
        "=== ЗАДАНИЕ ===\n"
        "Ответь сейчас на последнее сообщение пользователя как Лиза: кратко, по-русски, "
        "в своём стиле. Только твой ответ — без «Лиза:», без пересказа контекста, "
        "без кавычек вокруг всего ответа.\n"
        "Если последний вопрос — о твоих возможностях («что ты умеешь» и т.п.) — ответь "
        "структурированным списком функциональных возможностей ИЗ СЕКЦИИ ВОЗМОЖНОСТИ СИСТЕМЫ: "
        "домен + пример фразы (например: «OLX — создание и публикация объявлений: "
        "напиши „создай объявление …"
        ", „мониторинг цен"
        "»; «Склад — „добавь деталь …"
        ", "
        "„что на складе"
        "»; «Финансы — „запиши продажу …"
        "» и т.д.). В конце спроси, что сделать."
    )

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = "…" + text[-max_chars:]
    return text


# ---------------------------------------------------------------------------
# Ядро (async): вкладка -> временный чат -> запрос -> ответ
# ---------------------------------------------------------------------------


async def _click_new_chat(page) -> bool:
    """Открыть свежий чат. Приоритет — «Временный чат» (не пишется в историю)."""
    labels = ("Временный чат", "Temporary chat", "Новый чат", "New chat")
    for label in labels:
        loc = page.locator(f'button[aria-label="{label}"]').first
        try:
            await loc.click(timeout=3000)
            return True
        except Exception:
            continue
    # fallback: любой элемент с таким aria-label (могут быть ссылки/items)
    for label in labels:
        loc = page.locator(f'[aria-label="{label}"]').first
        try:
            await loc.click(timeout=2500)
            return True
        except Exception:
            continue
    return False


async def _wait_for_answer(page, prompt: str, timeout: int) -> str:
    """Дождаться завершения генерации и вернуть текст последнего хода модели."""
    t0 = time.time()
    last = ""
    stable = 0.0
    prompt_norm = (prompt or "").strip()

    while time.time() - t0 < timeout:
        try:
            stop_count = await page.locator(
                "button[aria-label='Остановить'], button[aria-label='Stop']"
            ).count()
        except Exception:
            stop_count = 0

        try:
            turns = await page.evaluate(_EXTRACT_JS)
        except Exception:
            turns = []

        cur = ""
        for t in turns:
            role = (t.get("role") or "").strip().lower()
            txt = (t.get("text") or "").strip()
            if not txt:
                continue
            if role in ("model", "assistant"):
                cur = txt
            elif role == "" and not cur:
                cur = txt  # последний ход без роли (старые версии UI)
        if cur == prompt_norm or (
            prompt_norm and cur == prompt_norm[: len(cur)] and len(cur) > 50
        ):
            cur = ""  # это эхо нашего запроса, а не ответ

        if cur and cur != last:
            last = cur
            stable = 0.0
        elif cur and cur == last:
            stable += 0.5
            if stable >= 3.0 and not stop_count:
                return cur
        else:
            stable = 0.0

        await page.wait_for_timeout(500)

    return last


async def _ask_gemini_async(prompt: str, timeout: int, cdp_url: str) -> str:
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright не установлен")
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        try:
            await page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)

            if "accounts.google.com" in page.url:
                raise RuntimeError(
                    "Google-сессия не активна: открылась страница входа. "
                    "Залогиньтесь в Chrome-профиле data/chrome_twin/default (VNC :1)."
                )

            new_chat = await _click_new_chat(page)
            if not new_chat:
                print(
                    "  [gemini_web] ⚠️ кнопка нового/временного чата не найдена — шлю в текущий чат"
                )

            box = page.locator("div[role=textbox]").first
            await box.click(timeout=8000)
            await page.wait_for_timeout(300)
            await page.keyboard.insert_text(
                prompt
            )  # быстро, работает с contenteditable
            await page.wait_for_timeout(200)
            await page.keyboard.press("Enter")

            answer = await _wait_for_answer(page, prompt, timeout)
            answer = (answer or "").strip()
            if not answer:
                raise RuntimeError("Gemini не вернул текст ответа (таймаут)")
            return answer
        finally:
            with contextlib.suppress(Exception):
                await page.close()


# ---------------------------------------------------------------------------
# Публичный синхронный API (с глобальным замком — один общий Chrome)
# ---------------------------------------------------------------------------

_LOCK_FILE = Path(__file__).resolve().parents[1] / "data" / ".gemini_web.lock"


def _cdp_alive(cdp_url: str, timeout: float = 3.0) -> bool:
    """Быстрая проверка, что Chrome с CDP доступен (HTTP GET /json/version)."""
    try:
        import urllib.request

        with urllib.request.urlopen(cdp_url + "/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def gemini_web_ask(prompt: str, timeout: int = 240, cdp_url: str = "") -> str:
    """Синхронно получить ответ Gemini Web.

    Сериализовано потоковым замком (внутри процесса) и файловым локом
    (между процессами — бот и CLI/скрипты не конфликтуют за вкладки).
    Если Chrome/CDP недоступен — сразу поднимаем ошибку (быстрый фолбэк),
    не тратя время на retry-петлю.
    """
    url = cdp_url or os.environ.get("AIOS_CHROME_CDP") or _CDP_DEFAULT
    if not _cdp_alive(url):
        raise RuntimeError("Chrome/CDP недоступен (127.0.0.1:9222) — быстрый фолбэк")
    with _lock:
        import asyncio
        import fcntl

        try:
            _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            _lf = open(_LOCK_FILE, "w")  # noqa: SIM115 - lock-файл держим открытым намеренно (flock)
        except Exception:
            _lf = None
        if _lf is not None:
            with contextlib.suppress(Exception):
                fcntl.flock(_lf, fcntl.LOCK_EX)  # межпроцессный замок (ждём)
        try:
            _last_err = None
            for _attempt in range(3):
                try:
                    return asyncio.run(_ask_gemini_async(prompt, timeout, url))
                except Exception as _e:
                    _last_err = _e
                    msg = str(_e)
                    if (
                        "closed" in msg.lower()
                        or "target" in msg.lower()
                        or "browser" in msg.lower()
                    ):
                        print(
                            f"  [gemini_web] попытка {_attempt + 1} не удалась ({msg[:80]}), повторяю…"
                        )
                        time.sleep(1.5)
                        continue
                    raise
            raise _last_err if _last_err else RuntimeError("Gemini Web недоступен")
        finally:
            if _lf is not None:
                try:
                    fcntl.flock(_lf, fcntl.LOCK_UN)
                    _lf.close()
                except Exception:
                    pass


def gemini_web_status(cdp_url: str = "") -> dict[str, Any]:
    """Проверка: Chrome на :9222 жив? Google-сессия активна? (открывает вкладку)."""
    url = cdp_url or os.environ.get("AIOS_CHROME_CDP") or _CDP_DEFAULT
    res: dict[str, Any] = {"chrome": False, "logged_in": False, "url": "", "error": ""}
    if not HAS_PLAYWRIGHT:
        res["error"] = "Playwright не установлен"
        return res
    try:
        import asyncio

        asyncio.run(_status_async(res, url))
    except Exception as e:
        res["error"] = str(e)[:200]
    return res


async def _status_async(res: dict[str, Any], cdp_url: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        try:
            await page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            res["chrome"] = True
            res["url"] = page.url
            if "accounts.google.com" in page.url:
                res["logged_in"] = False
            else:
                res["logged_in"] = await page.locator("div[role=textbox]").count() > 0
        finally:
            with contextlib.suppress(Exception):
                await page.close()


# ---------------------------------------------------------------------------
# CLI: python aios_core/llm_gemini_web.py --ask "..." | --status
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    _p = argparse.ArgumentParser(description="Gemini Web LLM adapter")
    _p.add_argument("--ask", default="", help="промпт для Gemini")
    _p.add_argument("--status", action="store_true", help="проверка Chrome/логина")
    _p.add_argument("--timeout", type=int, default=240)
    _args = _p.parse_args()

    if _args.status:
        print(json.dumps(gemini_web_status(), ensure_ascii=False, indent=2))
    elif _args.ask:
        print(gemini_web_ask(_args.ask, timeout=_args.timeout))
    else:
        _p.print_help()
