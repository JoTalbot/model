#!/usr/bin/env python3
"""
AIOS Daily Digest — утренний отчёт: почта + события дня + статистика Instagram.
Отправляет в Telegram по расписанию (systemd timer) или вручную.

Использование:
  python run_digest.py            — собрать и отправить дайджест (chat из .env)
  python run_digest.py --chat ID  — отправить в конкретный чат
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("OCTOPUS_ROOT", str(Path(__file__).resolve().parents[2])))


def _env(key: str) -> str:
    if key in ("AIOS_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN"):
        from swarm.tgbot.credentials import secret_from_env_or_credential

        value = secret_from_env_or_credential(
            "AIOS_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", credential="telegram_token"
        )
        if value:
            return value
    if key in ("TELEGRAM_CHAT_ID", "AIOS_OWNER_CHAT_ID", "AIOS_AUTO_CODER_CHAT_ID"):
        from swarm.tgbot.credentials import read_systemd_credential

        value = read_systemd_credential("telegram_owner_chat_id")
        if value:
            return value
    v = os.environ.get(key, "")
    if v:
        return v
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _tg(method: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _tg_photo(token: str, chat_id: int, path: str, caption: str = "") -> None:
    boundary = "----aiosd" + str(int(time.time() * 1000))
    content = Path(path).read_bytes()

    def field(name, value):
        return (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()

    body = b"".join(
        [
            field("chat_id", str(chat_id)),
            field("caption", caption[:900]) if caption else b"",
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
                f'filename="{Path(path).name}"\r\nContent-Type: image/png\r\n\r\n'
            ).encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        json.loads(r.read())


def _run_ac(args, timeout=170) -> dict:
    """Вызвать run_account_control.py (браузерные — под xvfb)."""
    py = sys.executable
    needs_x = not (
        len(args) >= 2
        and args[0] == "google"
        and args[1] in ("gmail_list", "gmail_send", "gmail_search", "open")
    )
    cmd = (
        (
            [
                "xvfb-run",
                "-a",
                "-s",
                "-screen 0 1440x900x24",
                py,
                str(ROOT / "run_account_control.py"),
                *args,
            ]
        )
        if needs_x
        else [py, str(ROOT / "run_account_control.py"), *args]
    )
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT)
        )
        out = (r.stdout or "").strip()
        start = out.find("{")
        return (
            json.loads(out[start:])
            if start >= 0
            else {"status": "error", "error": out[-300:]}
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


def _esc(s) -> str:
    import html

    return html.escape(str(s or ""))


def build_digest() -> tuple[str, list[str]]:
    """Собрать текст дайджеста + скриншоты. (text, [screenshots])"""
    import run_account_control as rac

    parts = []
    shots: list[str] = []
    today = datetime.now().strftime("%d.%m.%Y")

    # ---- Почта ----
    try:
        g = rac.gmail_list(6)
        if g.get("status") == "ok":
            emails = g.get("emails") or []
            unread = g.get("unread_total", 0)
            total = g.get("total", 0)
            head = (
                f"📥 <b>Почта</b> ({today})\n"
                f"Всего писем: {total} · 🔴 непрочитанных: {unread}"
            )
            lines = [head]
            for i, e in enumerate(emails[:5], 1):
                mark = "🔴 " if e.get("unread") else ""
                lines.append(
                    f"{i}. {mark}<b>{_esc(e.get('subject', '?'))}</b>\n   ✉️ {_esc(e.get('from', '?'))}"
                )
            parts.append("\n\n".join(lines))
        else:
            parts.append(f"📥 Почта: {_esc(g.get('error', 'ошибка'))}")
    except Exception as e:
        parts.append(f"📥 Почта: {_esc(e)}")

    # ---- Календарь ----
    try:
        cal = _run_ac(["google", "calendar_events"])
        if cal.get("status") == "ok":
            evs = cal.get("events") or []
            if evs:
                parts.append(
                    "📅 <b>События на сегодня:</b>\n"
                    + "\n".join(f"• {_esc(x)}" for x in evs)
                )
            else:
                parts.append("📅 Событий на сегодня нет.")
            if cal.get("screenshot") and Path(cal["screenshot"]).exists():
                shots.append(cal["screenshot"])
        else:
            parts.append(f"📅 Календарь: {_esc(cal.get('error', 'ошибка'))}")
    except Exception as e:
        parts.append(f"📅 Календарь: {_esc(e)}")

    # ---- Instagram ----
    try:
        ig = _run_ac(["instagram", "profile"])
        if ig.get("status") == "ok":
            p = ig.get("profile", {})
            parts.append(
                f"📸 <b>Instagram @{_esc(p.get('username', '?'))}</b>\n"
                f"👥 Подписчики: {p.get('followers') or 0} · "
                f"🔄 Подписки: {p.get('following') or 0} · "
                f"📄 Постов: {p.get('posts_count') or 0}"
            )
            if ig.get("screenshot") and Path(ig["screenshot"]).exists():
                shots.append(ig["screenshot"])
        else:
            parts.append(f"📸 Instagram: {_esc(ig.get('error', 'ошибка'))}")
    except Exception as e:
        parts.append(f"📸 Instagram: {_esc(e)}")

    text = "☀️ <b>AIOS Дайджест</b> — " + today + "\n\n" + "\n\n".join(parts)
    return text, shots


def send_digest(token: str, chat_id: int) -> None:
    text, shots = build_digest()
    _tg(
        "sendMessage",
        token,
        {
            "chat_id": chat_id,
            "text": text[:3900],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    for i, s in enumerate(shots):
        with contextlib.suppress(Exception):
            _tg_photo(token, chat_id, s, caption=f"📸 {i + 1}/{len(shots)}")


def main() -> None:
    token = _env("TELEGRAM_BOT_TOKEN") or _env("AIOS_TELEGRAM_TOKEN")
    if not token:
        print("Нет токена")
        sys.exit(1)
    chat = None
    if "--chat" in sys.argv:
        chat = int(sys.argv[sys.argv.index("--chat") + 1])
    else:
        chat = int(_env("TELEGRAM_CHAT_ID") or 0)
    if not chat:
        print("Нет chat id")
        sys.exit(1)
    send_digest(token, chat)
    print(f"Дайджест отправлен в chat {chat}")


if __name__ == "__main__":
    main()
