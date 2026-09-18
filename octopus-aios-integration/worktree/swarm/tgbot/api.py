"""TelegramAPI — минимальный клиент Telegram Bot API (выделен из run_telegram_bot.py).

Polling-режим, JSON + multipart загрузка файлов (фото/документы/голос).
"""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path

import requests
from urllib3.util import connection as urllib3_connection


# The server's IPv6 route to api.telegram.org intermittently stalls on larger
# POST bodies. Keep Telegram JSON requests on IPv4; this also applies to
# requests/urllib3 clients created later in the bot process.
def _telegram_ipv4_family() -> int:
    return socket.AF_INET


urllib3_connection.allowed_gai_family = _telegram_ipv4_family


class TelegramAPIError(RuntimeError):
    """Definitive Bot API rejection received as a complete response."""


class TelegramTransportError(RuntimeError):
    """Value-free transport failure after a Telegram request may have started."""


class TelegramAPI:
    """Minimal Telegram Bot API client (polling mode)."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._base = f"https://api.telegram.org/bot{token}"

    def _request(self, method: str, data: dict | None = None) -> dict:
        url = f"{self._base}/{method}"
        # getUpdates holds the response for up to 30 seconds by design. Other
        # Bot API methods must fail promptly instead of blocking all polling.
        timeout = (5, 40) if method == "getUpdates" else (5, 20)
        try:
            response = requests.post(url, json=data or {}, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as exc:
            status = int(getattr(exc.response, "status_code", 0) or 0)
            if status and status < 500:
                raise TelegramAPIError(f"Telegram {method} HTTP {status}") from None
            raise TelegramTransportError(
                f"Telegram {method} transport HTTP {status or 'unknown'}"
            ) from None
        except (requests.RequestException, ValueError) as exc:
            raise TelegramTransportError(
                f"Telegram {method} transport {type(exc).__name__}"
            ) from None
        if payload.get("ok") is False:
            code = int(payload.get("error_code") or 0)
            raise TelegramAPIError(f"Telegram {method} rejected with code {code}")
        return payload

    def get_updates(self, offset: int = 0) -> list[dict]:
        result = self._request("getUpdates", {"offset": offset, "timeout": 30})
        return result.get("result", [])

    def get_me(self) -> dict:
        """Non-invasive Bot API authentication/network canary."""
        return self._request("getMe")

    def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
        disable_notification: bool = False,
        reply_to_message_id: int | None = None,
    ) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if disable_notification:
            payload["disable_notification"] = True
        if reply_to_message_id:
            payload["reply_to_message_id"] = int(reply_to_message_id)
        return self._request("sendMessage", payload)

    def delete_message(self, chat_id: int, message_id: int) -> dict:
        return self._request(
            "deleteMessage", {"chat_id": chat_id, "message_id": message_id}
        )

    def send_chat_action(self, chat_id: int, action: str = "typing") -> dict:
        """Show a short Telegram activity indicator while a reply is generated."""
        return self._request("sendChatAction", {"chat_id": chat_id, "action": action})

    def edit_message(
        self,
        chat_id: int,
        msg_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> dict:
        payload: dict = {
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._request("editMessageText", payload)

    def answer_callback(self, callback_query_id: str, text: str = "") -> dict:
        return self._request(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text},
        )

    def get_file(self, file_id: str) -> dict:
        return self._request("getFile", {"file_id": file_id})

    def download_file_by_id(self, file_id: str, dest: str = "") -> str:
        info = self.get_file(file_id)
        path = info.get("result", {}).get("file_path", "")
        if not path:
            raise ValueError(f"Нет file_path для file_id {file_id}")
        url = f"https://api.telegram.org/file/bot{self._token}/{path}"
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                data = resp.read()
        except Exception as exc:
            raise TelegramTransportError(
                f"Telegram getFile transport {type(exc).__name__}"
            ) from None
        if not dest:
            ext = Path(path).suffix or ".jpg"
            dest = f"/tmp/aios_tg_{int(__import__('time').time() * 1000)}{ext}"
        Path(dest).write_bytes(data)
        return dest

    def _multipart(
        self, method: str, chat_id: int, field: str, file_path: str, caption: str = ""
    ) -> dict:
        """Универсальная отправка файла (photo/document)."""
        import mimetypes

        boundary = "----aios" + str(int(__import__("time").time() * 1000))
        content = Path(file_path).read_bytes()

        def _field(name: str, value: str) -> bytes:
            return (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()

        fn = Path(file_path).name
        ct = mimetypes.guess_type(fn)[0] or "application/octet-stream"
        body = b"".join(
            [
                _field("chat_id", str(chat_id)),
                _field("caption", caption[:1000]) if caption else b"",
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{fn}"\r\n'
                    f"Content-Type: {ct}\r\n\r\n"
                ).encode(),
                content,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        req = urllib.request.Request(
            f"{self._base}/{method}",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.loads(resp.read())
        except Exception as exc:
            raise TelegramTransportError(
                f"Telegram {method} transport {type(exc).__name__}"
            ) from None
        if payload.get("ok") is False:
            raise TelegramAPIError(
                f"Telegram {method} rejected with code {int(payload.get('error_code') or 0)}"
            )
        return payload

    def send_photo(self, chat_id: int, photo_path: str, caption: str = "") -> dict:
        return self._multipart("sendPhoto", chat_id, "photo", photo_path, caption)

    def send_document(self, chat_id: int, file_path: str, caption: str = "") -> dict:
        return self._multipart("sendDocument", chat_id, "document", file_path, caption)

    def send_voice(self, chat_id: int, voice_path: str, caption: str = "") -> dict:
        return self._multipart("sendVoice", chat_id, "voice", voice_path, caption)
