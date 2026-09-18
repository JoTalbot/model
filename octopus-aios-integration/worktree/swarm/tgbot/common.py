"""Общие хелперы Telegram-бота (выделено из run_telegram_bot.py)."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
DATA_DIR = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))


def _safe(fn):
    """Wrapper — catch all exceptions, return error string."""

    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            import traceback

            traceback.print_exc()
            return f"❌ Ошибка: {exc}"

    return wrapper


def _esc_tg(s) -> str:
    import html

    return html.escape(str(s or ""))


def _smart_model() -> str:
    """Умная модель для чата владельца с авто-переключением по нагрузке.

    Пока клиентов/сессий мало — gemini-2.5-pro (максимальное качество);
    при большом потоке — gemini-2.5-flash (дешевле). Явный выбор через
    AIOS_PLANNER_MODEL переопределяет всё.
    """
    override = os.environ.get("AIOS_PLANNER_MODEL", "").strip()
    if override:
        return override
    threshold = int(os.environ.get("AIOS_SMART_MODEL_THRESHOLD", "10") or 10)
    try:
        _sdir = PROJECT_ROOT / "data" / "autonomy_sessions"
        active = len(list(_sdir.glob("*.json"))) if _sdir.exists() else 0
    except Exception:
        active = 0
    return "gemini-2.5-flash" if active >= threshold else "gemini-2.5-pro"


@_safe
def _local_api_json(path: str) -> dict:
    """Read a trusted local AIOS API endpoint for Telegram status commands."""
    with urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=10) as response:
        return json.loads(response.read())


def _run_account_control(args: list[str], timeout: int = 160) -> dict:
    """Запустить run_account_control.py (хелпер управления аккаунтами)."""
    import subprocess as _sp

    py = sys.executable
    helper = str(PROJECT_ROOT / "run_account_control.py")
    # IMAP/SMTP-команды не требуют X; браузерные — требуют xvfb
    # viber — нативный десктоп на постоянном дисплее :1 (без xvfb)
    if args and args[0] in ("viber", "signal"):
        needs_x = False
    else:
        needs_x = not (
            len(args) >= 2
            and args[0] == "google"
            and args[1] in ("gmail_list", "gmail_send", "gmail_search", "open")
        )
    if needs_x:
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1440x900x24", py, helper, *args]
    else:
        cmd = [py, helper, *args]
    try:
        r = _sp.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=str(PROJECT_ROOT)
        )
    except _sp.TimeoutExpired:
        return {
            "status": "error",
            "error": "Превышено время выполнения (браузер может быть занят)",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}
    out_txt = (r.stdout or "").strip()
    if not out_txt:
        return {"status": "error", "error": (r.stderr or "пустой ответ")[-400:]}
    try:
        # JSON может быть последней строкой или всем выводом
        start = out_txt.find("{")
        return (
            json.loads(out_txt[start:])
            if start >= 0
            else {"status": "error", "error": out_txt[-400:]}
        )
    except Exception:
        return {"status": "error", "error": out_txt[-400:]}
