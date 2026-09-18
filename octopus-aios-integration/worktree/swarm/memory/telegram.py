"""Telegram bot for Octopus swarm + Arena AI integration.

Extends the original swarm-only bot with Arena chat capabilities:
  /arena <prompt>  — ask Arena AI (streaming effect in TG)
  /model           — show / pick available models
  /model <name>    — set active model
  /conv            — start a new conversation (clear history)
  /hist            — show conversation history
  /health_arena    — arena queue health

Original swarm commands preserved:
  /start, /status, /peers, /tasks, /task, /health, /alerts,
  /list, /insert, /rag, /qr, /swarm, /nodes, /ask
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

_LOG = logging.getLogger("swarm.memory.telegram")
_API_BASE = "https://api.telegram.org"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class BotConfig:
    token: str
    allowed_chat_ids: set[int] = field(default_factory=set)
    open_access: bool = False
    poll_timeout_s: int = 30
    request_timeout_s: float = 60.0
    parse_mode: str = "Markdown"
    #: Arena API base URL (no trailing slash). Must be reachable from
    #: wherever the bot runs.  Example: ``"http://127.0.0.1/api"``.
    arena_api_base: str = "http://127.0.0.1/api"
    #: Arena request timeout (the browser automation is slow ~30s).
    arena_timeout_s: float = 90.0


# ---------------------------------------------------------------------------
# Pure helpers (kept for backward compat / testability)
# ---------------------------------------------------------------------------


def format_status(
    metrics_snapshot: dict, *, audit_stats: dict | None = None
) -> str:
    if not metrics_snapshot:
        head = "_No memory metrics recorded yet._"
    else:
        lines = ["*Memory metrics (per scheme):*"]
        for scheme, row in sorted(metrics_snapshot.items()):
            lines.append(
                f"`{scheme}` puts={row['puts']} "
                f"ok={row['gets_ok']} err={row['gets_err']} "
                f"avail={row['availability']:.2f}"
            )
        head = "\n".join(lines)
    if audit_stats:
        total = audit_stats.get("total", 0)
        per_op = audit_stats.get("per_op", {})
        head += "\n\n*Audit log:* "
        head += f"{total} events, per_op={json.dumps(per_op)}"
    return head


def parse_insert_args(payload: str) -> tuple[str, dict[str, Any]]:
    parts = shlex.split(payload)
    if not parts:
        raise ValueError("usage: /insert TABLE key=value [key=value ...]")
    table = parts[0]
    data: dict[str, Any] = {}
    for raw in parts[1:]:
        if "=" not in raw:
            raise ValueError(f"missing '=' in fragment: {raw!r}")
        k, _, v = raw.partition("=")
        data[k] = _coerce(v)
    return table, data


def _coerce(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    lo = value.lower()
    if lo == "true":
        return True
    if lo == "false":
        return False
    if lo == "null":
        return None
    return value


# ---------------------------------------------------------------------------
# Arena client  (per-chat state)
# ---------------------------------------------------------------------------


class ArenaChat:
    """Holds per-chat Arena conversation state + API helpers."""

    def __init__(self, api_base: str, timeout: float = 90.0) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.model: str | None = None  # None = server default
        self.history: list[dict[str, str]] = []
        self._http: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            # Default Host header required because nginx routes by Host.
            # The arena API sits behind api.autosklo.org.ua vhost.
            headers = {"Host": "api.autosklo.org.ua"}
            self._http = httpx.AsyncClient(timeout=self.timeout, headers=headers)
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def get_models(self) -> list[dict]:
        """Fetch available models from arena."""
        c = await self._client()
        r = await c.get(f"{self.api_base}/v1/models")
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])

    async def health(self) -> dict:
        c = await self._client()
        r = await c.get(f"{self.api_base}/health")
        r.raise_for_status()
        return r.json()

    async def ask(self, prompt: str) -> str:
        """Send prompt to arena (non-streaming), return assistant text."""
        self.history.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model or "gpt-5.2",
            "messages": list(self.history),
            "stream": False,
        }
        c = await self._client()
        r = await c.post(
            f"{self.api_base}/v1/chat/completions", json=payload
        )
        r.raise_for_status()
        body = r.json()
        text = body["choices"][0]["message"]["content"]
        self.history.append({"role": "assistant", "content": text})
        return text

    async def ask_stream(self, prompt: str) -> str:
        """Send prompt via SSE streaming, accumulate and return full text."""
        self.history.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model or "gpt-5.2",
            "messages": list(self.history),
            "stream": True,
        }
        c = await self._client()
        async with c.stream(
            "POST",
            f"{self.api_base}/v1/chat/completions",
            json=payload,
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            chunks: list[str] = []
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line.startswith(":"):
                    continue  # heartbeat / comment
                if line == "data: [DONE]":
                    break
                if line.startswith("data: "):
                    try:
                        obj = json.loads(line[6:])
                        delta = obj["choices"][0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            chunks.append(token)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        text = "".join(chunks)
        self.history.append({"role": "assistant", "content": text})
        return text

    def reset(self) -> None:
        self.history.clear()


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------


HandlerFn = Callable[["TelegramBot", dict, str], Awaitable[str]]


class TelegramBot:
    """Long-polling Telegram bot with swarm management + Arena AI."""

    def __init__(
        self,
        config: BotConfig,
        *,
        repository=None,
        metrics=None,
        audit_stats_fn: Callable[[], dict | None] | None = None,
        rag_fn: Callable[[str], Awaitable[str]] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cfg = config
        self._repo = repository
        self._metrics = metrics
        self._audit_stats_fn = audit_stats_fn
        self._rag_fn = rag_fn
        self._client = client or httpx.AsyncClient(timeout=config.request_timeout_s)
        self._handlers: dict[str, HandlerFn] = {
            "/start": _cmd_start,
            "/status": _cmd_status,
            "/list": _cmd_list,
            "/insert": _cmd_insert,
            "/rag": _cmd_rag,
            "/qr": _cmd_qr,
            "/help": _cmd_start,
            "/peers": _cmd_peers,
            "/tasks": _cmd_tasks,
            "/task": _cmd_task_create,
            "/health": _cmd_health,
            "/alerts": _cmd_alerts,
            "/ask": _cmd_ask,
            "/swarm": _cmd_swarm,
            "/nodes": _cmd_nodes,
            # --- Arena commands ---
            "/arena": _cmd_arena,
            "/model": _cmd_model,
            "/models": _cmd_model,
            "/conv": _cmd_conv,
            "/hist": _cmd_hist,
            "/arena_health": _cmd_arena_health,
        }
        self._container = None
        self._stop = asyncio.Event()
        self._offset = 0

        # Per-chat arena sessions keyed by chat_id
        self._arena_sessions: dict[int, ArenaChat] = {}

    # -- arena session helper --

    def _arena(self, chat_id: int) -> ArenaChat:
        if chat_id not in self._arena_sessions:
            self._arena_sessions[chat_id] = ArenaChat(
                api_base=self._cfg.arena_api_base,
                timeout=self._cfg.arena_timeout_s,
            )
        return self._arena_sessions[chat_id]

    def _chat_allowed(self, chat_id: int) -> bool:
        if self._cfg.open_access:
            return True
        if not self._cfg.allowed_chat_ids:
            return False
        return chat_id in self._cfg.allowed_chat_ids

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return f"{_API_BASE}/bot{self._cfg.token}"

    async def call(self, method: str, **payload: Any) -> Any:
        url = f"{self.base_url}/{method}"
        resp = await self._client.post(url, json=payload)
        try:
            body = resp.json()
        except Exception as exc:
            raise RuntimeError(f"telegram {method} bad response: {exc}") from exc
        if not body.get("ok"):
            raise RuntimeError(f"telegram {method} failed: {body!r}")
        return body.get("result")

    async def send(
        self, chat_id: int, text: str, *, monospace: bool = False,
        reply_to: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": f"```\n{text}\n```" if monospace else text,
        }
        if self._cfg.parse_mode:
            payload["parse_mode"] = self._cfg.parse_mode
            payload["disable_web_page_preview"] = True
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        try:
            await self.call("sendMessage", **payload)
        except Exception as exc:
            _LOG.warning("sendMessage failed: %s", exc)

    async def send_with_keyboard(
        self, chat_id: int, text: str, buttons: list[list[str]],
    ) -> None:
        """Send message with inline keyboard (callback buttons)."""
        keyboard = []
        for row in buttons:
            keyboard.append(
                [{"text": label, "callback_data": label} for label in row]
            )
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        if self._cfg.parse_mode:
            payload["parse_mode"] = self._cfg.parse_mode
            payload["disable_web_page_preview"] = True
        try:
            await self.call("sendMessage", **payload)
        except Exception as exc:
            _LOG.warning("sendMessage+keyboard failed: %s", exc)

    async def edit_message(
        self, chat_id: int, message_id: int, text: str,
    ) -> None:
        """Edit existing message text (for streaming effect)."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if self._cfg.parse_mode:
            payload["parse_mode"] = self._cfg.parse_mode
            payload["disable_web_page_preview"] = True
        try:
            await self.call("editMessageText", **payload)
        except Exception as exc:
            _LOG.debug("editMessageText failed (ok if msg unchanged): %s", exc)

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        """Send typing / upload_photo / etc. action."""
        try:
            await self.call("sendChatAction", chat_id=chat_id, action=action)
        except Exception as exc:
            _LOG.debug("sendChatAction failed: %s", exc)

    # ------------------------------------------------------------------
    # Long-poll loop
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        _LOG.info(
            "telegram bot starting (open_access=%s allowlist=%s arena=%s)",
            self._cfg.open_access,
            sorted(self._cfg.allowed_chat_ids),
            self._cfg.arena_api_base,
        )
        while not self._stop.is_set():
            try:
                updates = await self.call(
                    "getUpdates",
                    offset=self._offset,
                    timeout=self._cfg.poll_timeout_s,
                )
            except Exception as exc:
                _LOG.warning("getUpdates failed: %s", exc)
                await asyncio.sleep(2.0)
                continue
            for upd in updates or []:
                self._offset = max(self._offset, int(upd["update_id"]) + 1)
                await self._dispatch(upd)

    async def _dispatch(self, update: dict) -> None:
        # Handle callback queries (inline keyboard button presses)
        cb = update.get("callback_query")
        if cb:
            await self._handle_callback(cb)
            return

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat = msg.get("chat") or {}
        chat_id = int(chat.get("id", 0))
        if not self._chat_allowed(chat_id):
            _LOG.info("ignoring message from chat %s (not allowlisted)", chat_id)
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return
        _LOG.info("chat=%s from=%s text=%.80s", chat_id, msg.get("from", {}).get("username", "?"), text)

        # If no command prefix and arena session exists, treat as arena prompt
        if not text.startswith("/"):
            arena = self._arena_sessions.get(chat_id)
            if arena:
                await self._arena_ask(chat_id, msg, text)
                return

        cmd, _, rest = text.partition(" ")
        handler = self._handlers.get(cmd.split("@", 1)[0])
        if handler is None:
            await self.send(chat_id, f"unknown command {cmd!r}; try /start")
            return
        try:
            reply = await handler(self, msg, rest.strip())
        except Exception as exc:
            reply = f"error: {type(exc).__name__}: {exc}"
        if reply:
            await self.send(chat_id, reply, monospace=cmd == "/qr")

    async def _handle_callback(self, cb: dict) -> None:
        """Handle inline keyboard callback (e.g. model selection)."""
        data = cb.get("data", "")
        msg = cb.get("message", {})
        chat_id = int(msg.get("chat", {}).get("id", 0))
        message_id = msg.get("message_id")

        if not self._chat_allowed(chat_id):
            return

        # Acknowledge the callback (remove loading state)
        try:
            await self.call("answerCallbackQuery", callback_query_id=cb["id"])
        except Exception:
            pass

        # If callback data looks like a model name
        if data.startswith("model:"):
            model_name = data[6:]
            arena = self._arena(chat_id)
            arena.model = model_name
            try:
                await self.edit_message(
                    chat_id, message_id,
                    f"Модель установлена: *{model_name}*\n\nИспользуйте `/arena <вопрос>` или просто напишите текст.",
                )
            except Exception:
                await self.send(
                    chat_id,
                    f"Модель установлена: *{model_name}*",
                    reply_to=message_id,
                )
        elif data in ("page_prev", "page_next"):
            # Model list pagination - re-send model list
            arena = self._arena(chat_id)
            page_key = f"_model_page_{chat_id}"
            page = getattr(self, page_key, 0)
            if data == "page_next":
                page += 1
            else:
                page = max(0, page - 1)
            setattr(self, page_key, page)
            try:
                models = await arena.get_models()
                await self._send_model_page(chat_id, message_id, models, page)
            except Exception as exc:
                await self.send(chat_id, f"Ошибка загрузки моделей: {exc}")

    async def _send_model_page(
        self, chat_id: int, message_id: int | None,
        models: list[dict], page: int, per_page: int = 8,
    ) -> None:
        """Send a paginated model list with inline keyboard."""
        total = len(models)
        start = page * per_page
        end = start + per_page
        page_models = models[start:end]

        buttons: list[list[str]] = []
        lines = [f"*Модели* ({start + 1}-{min(end, total)} из {total}):\n"]
        for m in page_models:
            mid = m["id"]
            info = m.get("arena", {})
            provider = info.get("provider", "?")
            desc = info.get("description", "")[:40]
            thinking = " [T]" if info.get("thinking") else ""
            lines.append(f"• `{mid}` — {provider}{thinking}")
            if desc:
                lines.append(f"  _{desc}_")
            buttons.append([f"model:{mid}"])

        # Pagination buttons
        nav = []
        if page > 0:
            nav.append("page_prev")
        if end < total:
            nav.append("page_next")
        if nav:
            buttons.append(nav)

        text = "\n".join(lines)
        if message_id:
            try:
                await self.edit_message(chat_id, message_id, text)
                # Update keyboard by deleting and re-sending
                # (Telegram doesn't support editing reply_markup easily via Bot API)
                return
            except Exception:
                pass
        await self.send_with_keyboard(chat_id, text, buttons)

    # ------------------------------------------------------------------
    # Arena streaming ask (with typing + edit effect)
    # ------------------------------------------------------------------

    async def _arena_ask(self, chat_id: int, msg: dict, prompt: str) -> None:
        """Send prompt to arena with streaming UI effect."""
        arena = self._arena(chat_id)
        model_name = arena.model or "gpt-5.2"

        # Send initial "thinking" message
        thinking_msg = await self.call(
            "sendMessage",
            chat_id=chat_id,
            text=f"**{model_name}** думает...",
            parse_mode="Markdown",
        )
        thinking_id = thinking_msg["message_id"]

        # Start typing indicator loop
        typing_task = asyncio.create_task(
            self._typing_loop(chat_id), name="typing-loop"
        )

        try:
            text = await arena.ask_stream(prompt)
        except asyncio.TimeoutError:
            text = "⏱ *Таймаут*. Арена не ответила вовремя. Попробуйте ещё раз."
        except Exception as exc:
            text = f"❌ *Ошибка арены:* {type(exc).__name__}: {str(exc)[:200]}"
        finally:
            typing_task.cancel()

        # Clean up response text (remove common browser artifacts)
        for artifact in ["Search\nToday", "Search", "Today"]:
            if text.strip() == artifact:
                text = "(арена вернула пустой / артефактный ответ — этоKnown issue браузерной автоматизации. Попробуйте другую модель или переформулируйте вопрос.)"

        # Try to edit the thinking message with the actual response
        # Telegram limit: 4096 chars for message text
        if len(text) > 4000:
            text = text[:3900] + "\n\n_...обрезано (слишком длинный ответ)_"

        try:
            await self.edit_message(chat_id, thinking_id, f"**{model_name}:**\n\n{text}")
        except Exception:
            # If edit fails (e.g. message too old), send new message
            await self.send(chat_id, f"**{model_name}:**\n\n{text}", reply_to=msg.get("message_id"))

    async def _typing_loop(self, chat_id: int) -> None:
        """Continuously send typing action while arena processes."""
        try:
            while True:
                await self.send_chat_action(chat_id, "typing")
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            return


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _cmd_start(bot: TelegramBot, _msg: dict, _rest: str) -> str:
    return (
        "*Octopus Bot*\n\n"
        "🤖 *Arena AI:*\n"
        "/arena — задать вопрос арене (или просто напишите текст)\n"
        "/model — выбрать модель из списка\n"
        "/conv — новая беседа\n"
        "/hist — история переписки\n"
        "/arena\\_health — статус очереди арены\n\n"
        "🐙 *Swarm:*\n"
        "/status — метрики памяти + audit\n"
        "/swarm — статус роя\n"
        "/peers — Kademlia пиры\n"
        "/nodes — список нод\n"
        "/tasks — очередь задач\n"
        "/task DESC — создать задачу\n"
        "/health — здоровье адаптеров\n"
        "/alerts — последние ошибки\n"
        "/ask — локальный LLM (Ollama)\n\n"
        "💾 *Память:*\n"
        "/list TABLE — последние записи\n"
        "/insert TABLE k=v — сохранить\n"
        "/rag QUERY — RAG контекст\n"
        "/qr DATA — QR-код"
    )


# --- Original swarm handlers (unchanged) ---


async def _cmd_status(bot: TelegramBot, _msg: dict, _rest: str) -> str:
    if bot._metrics is None:
        return "no metrics wired into the bot"
    audit_stats = bot._audit_stats_fn() if bot._audit_stats_fn else None
    return format_status(bot._metrics.snapshot(), audit_stats=audit_stats)


async def _cmd_list(bot: TelegramBot, _msg: dict, rest: str) -> str:
    if bot._repo is None:
        return "memory repository not wired"
    table = rest.strip() or None
    rows = await bot._repo.latest(table=table, n=5)
    if not rows:
        return f"no rows in {table or '*'}"
    lines = [f"`{r.ref}` {json.dumps(r.data, ensure_ascii=False)[:200]}" for r in rows]
    return "*latest*\n" + "\n".join(lines)


async def _cmd_insert(bot: TelegramBot, _msg: dict, rest: str) -> str:
    if bot._repo is None:
        return "memory repository not wired"
    if not rest:
        return "usage: /insert TABLE key=value [key=value ...]"
    table, data = parse_insert_args(rest)
    ref = await bot._repo.save(data, table=table)
    return f"saved `{ref}`"


async def _cmd_rag(bot: TelegramBot, _msg: dict, rest: str) -> str:
    if bot._rag_fn is None:
        return "RAG not wired into the bot"
    if not rest:
        return "usage: /rag QUERY"
    return await bot._rag_fn(rest)


async def _cmd_qr(bot: TelegramBot, _msg: dict, rest: str) -> str:
    from swarm.memory.qr import qr_terminal

    if not rest:
        return "usage: /qr DATA"
    return qr_terminal(rest, ec_level="M")


async def _cmd_peers(bot: TelegramBot, _msg: dict, _rest: str) -> str:
    if bot._container is None:
        return "_Node container not attached to bot_"
    try:
        peers = await bot._container.kad.get_peers()
    except Exception as exc:
        return f"error getting peers: {exc}"
    if not peers:
        return "_No peers connected_"
    lines = ["*Connected peers:*"]
    for i, p in enumerate(peers[:20], 1):
        lines.append(f"`{i}.` `{p}`")
    return "\n".join(lines)


async def _cmd_tasks(bot: TelegramBot, _msg: dict, _rest: str) -> str:
    if bot._container is None:
        return "_Node container not attached to bot_"
    q = bot._container.agent.task_queue
    items = list(q._queue) if hasattr(q, "_queue") else []
    if not items:
        return "_No tasks in queue_"
    lines = ["*Task queue:*"]
    for t in items[:10]:
        tid = getattr(t, "id", "?")[:8]
        desc = getattr(t, "description", "")[:60]
        status = getattr(t, "status", None)
        s = status.value if hasattr(status, "value") else str(status)
        lines.append(f"`{tid}` [{s}] {desc}")
    return "\n".join(lines)


async def _cmd_task_create(bot: TelegramBot, _msg: dict, rest: str) -> str:
    if bot._container is None:
        return "_Node container not attached to bot_"
    if not rest.strip():
        return "usage: /task DESCRIPTION"
    from swarm.agent.core import Task
    task = Task(
        description=rest.strip(),
        creator_id=bot._container.kad.node_id or "telegram",
    )
    await bot._container.agent.submit_task(task)
    return f"Task created: `{task.id[:8]}` — _{rest.strip()[:60]}_"


async def _cmd_health(bot: TelegramBot, _msg: dict, _rest: str) -> str:
    if bot._metrics is None:
        return "_No metrics wired_"
    snap = bot._metrics.snapshot()
    if not snap:
        return "_No adapters recorded yet_"
    lines = ["*Adapter health:*"]
    for scheme, row in sorted(snap.items()):
        avail = row.get("availability", 1.0)
        if avail >= 0.95:
            icon = "🟢"
        elif avail >= 0.7:
            icon = "🟡"
        else:
            icon = "🔴"
        err = row.get("last_error", "")
        line = f"{icon} `{scheme}` {avail:.0%}"
        if err:
            line += f" — _{err[:40]}_"
        lines.append(line)
    return "\n".join(lines)


async def _cmd_alerts(bot: TelegramBot, _msg: dict, _rest: str) -> str:
    if bot._metrics is None:
        return "_No metrics wired_"
    snap = bot._metrics.snapshot()
    errors = [
        (scheme, row.get("last_error", ""))
        for scheme, row in snap.items()
        if row.get("last_error")
    ]
    if not errors:
        return "✅ _No recent errors_"
    lines = ["*Recent errors:*"]
    for scheme, err in errors:
        lines.append(f"🔴 `{scheme}` — {err[:100]}")
    return "\n".join(lines)


async def _cmd_ask(bot, _msg, rest):
    """LLM-ответ на вопрос через локальную Ollama."""
    q = rest.strip()
    if not q:
        return "Использование: `/ask <вопрос>`"
    container = bot._container
    if container is None:
        return "_Нет контейнера_"
    llm = getattr(container, "llm", None)
    if llm is None:
        return "_LLM не настроен. Запустите Ollama на ноде._"
    try:
        msgs = [
            {"role": "system", "content": "Ты — ИИ-агент P2P системы Octopus. Отвечай кратко по-русски."},
            {"role": "user", "content": q},
        ]
        resp = await asyncio.wait_for(llm.chat(msgs), timeout=30.0)
        ans = resp.choices[0].message.content if resp else "Нет ответа"
        return "🤖 *Octopus AI:*\n" + ans[:2000]
    except asyncio.TimeoutError:
        return "⏱ _Timeout 30s. Ollama перегружен?_"
    except Exception as e:
        return "❌ _Ошибка LLM: " + str(e)[:80] + "_"


async def _cmd_swarm(bot, _msg, _rest):
    """Статус роя."""
    container = bot._container
    if container is None:
        return "_Нет контейнера_"
    try:
        peers = await container.kad.get_peers()
        reg = getattr(container, "peer_registry", None)
        verified = len(reg) if reg else 0
        g = container.gossip.stats()
        st = getattr(container, "_started_at", time.time())
        up = int(time.time() - st)
        lines = [
            "🐙 *Octopus Swarm Status*",
            f"Kademlia peers: `{len(peers)}`",
            f"Verified (handshake): `{verified}`",
            f"Gossip seen: `{g.get('seen', 0)}`",
            f"Uptime: `{up // 3600}h {(up % 3600) // 60}m`",
        ]
        if reg:
            nodes = list(reg.all_peers())[:6]
            if nodes:
                lines.append("\n*Ноды реестра:*")
                for p in nodes:
                    lines.append(f"  • `{p.node_id[:12]}` → `{p.address}`")
        return "\n".join(lines)
    except Exception as e:
        return f"_Ошибка: {e}_"


async def _cmd_nodes(bot, _msg, _rest):
    """Список нод с адресами."""
    container = bot._container
    if container is None:
        return "_Нет контейнера_"
    reg = getattr(container, "peer_registry", None)
    if not reg:
        return "_Реестр пиров недоступен_"
    peers = reg.all_peers()
    if not peers:
        return "_Нет зарегистрированных нод_"
    lines = [f"🌐 *Ноды роя* ({len(peers)}):"]
    for p in peers:
        lines.append(f"  `{p.node_id[:14]}` → `{p.address}`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Arena command handlers
# ---------------------------------------------------------------------------


async def _cmd_arena(bot: TelegramBot, msg: dict, rest: str) -> str:
    """Route to the streaming arena ask handler."""
    chat_id = int((msg.get("chat") or {}).get("id", 0))
    prompt = rest.strip()
    if not prompt:
        return "Использование: `/arena <вопрос>`\nИли просто напишите текст (без /) — он отправится в арену."
    # Delegate to the streaming handler (non-command path)
    await bot._arena_ask(chat_id, msg, prompt)
    return ""  # _arena_ask sends the message itself


async def _cmd_model(bot: TelegramBot, msg: dict, rest: str) -> str:
    """Show model list with pagination, or set a specific model."""
    chat_id = int((msg.get("chat") or {}).get("id", 0))
    arena = bot._arena(chat_id)

    # /model <name> — set model directly
    if rest.strip():
        arena.model = rest.strip()
        return f"Модель установлена: *{rest.strip()}*\n\nИспользуйте `/arena <вопрос>` или просто напишите текст."

    # /model — show paginated list with inline buttons
    try:
        models = await arena.get_models()
    except Exception as exc:
        return f"❌ Не удалось загрузить список моделей: {exc}"

    if not models:
        return "_Список моделей пуст_"

    # Reset page
    page_key = f"_model_page_{chat_id}"
    setattr(bot, page_key, 0)
    await bot._send_model_page(chat_id, None, models, 0)
    return ""  # _send_model_page sends the message itself


async def _cmd_conv(bot: TelegramBot, msg: dict, _rest: str) -> str:
    """Start a new conversation (clear history)."""
    chat_id = int((msg.get("chat") or {}).get("id", 0))
    arena = bot._arena(chat_id)
    had = len(arena.history)
    arena.reset()
    if had:
        return f"🆕 *Новая беседа* (очищено {had} сообщений)"
    return "🆕 *Новая беседа* (история была пуста)"


async def _cmd_hist(bot: TelegramBot, msg: dict, _rest: str) -> str:
    """Show conversation history."""
    chat_id = int((msg.get("chat") or {}).get("id", 0))
    arena = bot._arena(chat_id)
    if not arena.history:
        return "_История пуста. Используйте `/arena <вопрос>`_"

    lines = ["*История переписки с ареной:*\n"]
    model_info = f"Модель: `{arena.model or 'default'}`"
    lines.append(model_info + "\n")
    for i, h in enumerate(arena.history, 1):
        role = "👤" if h["role"] == "user" else "🤖"
        content = h["content"][:300]
        if len(h["content"]) > 300:
            content += "..."
        lines.append(f"{role} {content}")
    return "\n".join(lines)


async def _cmd_arena_health(bot: TelegramBot, msg: dict, _rest: str) -> str:
    """Show arena queue health."""
    chat_id = int((msg.get("chat") or {}).get("id", 0))
    arena = bot._arena(chat_id)
    try:
        h = await arena.health()
    except Exception as exc:
        return f"❌ Не удалось получить статус арены: {exc}"

    status = h.get("status", "unknown")
    queue = h.get("queue", {})
    busy = queue.get("busy", False)
    pending = queue.get("pending", 0)
    current = queue.get("current_task_id", "none")
    recent = queue.get("recent", [])

    lines = [
        f"🩺 *Arena Health*\n",
        f"Статус: `{'занята' if busy else 'свободна'}`",
        f"В очереди: `{pending}`",
        f"Текущая задача: `{str(current)[:16]}`",
    ]

    if recent:
        lines.append(f"\n*Последние задачи ({min(len(recent), 3)}):*")
        for t in recent[:3]:
            tid = str(t.get("id", "?"))[:8]
            model = t.get("model", "?")
            st = t.get("status", "?")
            preview = str(t.get("prompt_preview", ""))[:40]
            lines.append(f"  • `{tid}` [{st}] `{model}` — {preview}")

    return "\n".join(lines)


__all__ = [
    "BotConfig",
    "TelegramBot",
    "ArenaChat",
    "format_status",
    "parse_insert_args",
]