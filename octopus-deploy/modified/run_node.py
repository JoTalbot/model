from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
import sys

import httpx

from swarm.bootstrap.config import load_config
from swarm.memory.repository import MemoryRepository
from swarm.memory.telegram import BotConfig, TelegramBot
from swarm.runtime import AppContainer, AppRuntime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("octopus-deploy-runner")


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_chat_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return out


async def _build_bot(container: AppContainer) -> tuple[TelegramBot | None, asyncio.Task | None]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None, None

    allowed_chat_ids = _parse_chat_ids(os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS"))
    open_access = _bool_env("TELEGRAM_OPEN_ACCESS", False)
    if not allowed_chat_ids and not open_access:
        log.warning("Telegram token is set, but allowlist is empty and open access is disabled")
        return None, None

    repo = MemoryRepository(container.agent.memory_port)
    metrics = getattr(container.agent.memory_port, "metrics", None)

    async def rag_fn(query: str) -> str:
        try:
            context = await container.graph_rag.retrieve_context(query, top_k=5)
            if not context.strip():
                return "_Контекст не найден_"
            return context[:3500]
        except Exception as exc:
            return f"RAG error: {type(exc).__name__}: {exc}"

    proxy = os.environ.get("TELEGRAM_PROXY", "").strip()
    client = httpx.AsyncClient(timeout=60.0, proxy=proxy) if proxy else None

    # --- Arena AI configuration ---
    # Default: use local nginx (port 80) with Host header routing.
    # The /api/ location block proxies to arena via the SSE fix proxy.
    arena_api_base = os.environ.get(
        "ARENA_API_BASE",
        "http://127.0.0.1/api",
    ).strip()

    bot = TelegramBot(
        BotConfig(
            token=token,
            allowed_chat_ids=allowed_chat_ids,
            open_access=open_access,
            arena_api_base=arena_api_base,
            arena_timeout_s=float(os.environ.get("ARENA_TIMEOUT_S", "120")),
        ),
        repository=repo,
        metrics=metrics,
        rag_fn=rag_fn,
        client=client,
    )
    bot._container = container

    async def status_handler(_bot, _msg, _rest: str) -> str:
        try:
            peers = await container.kad.get_peers()
        except Exception:
            peers = []
        all_rows = await repo.latest(n=20)
        notes = await repo.latest(table="notes", n=20)
        files = await repo.latest(table="files", n=20)
        tasks_q = container.agent.task_queue
        tasks = list(tasks_q._queue) if hasattr(tasks_q, "_queue") else []
        snap = metrics.snapshot() if metrics is not None else {}
        lines = [
            "*Octopus node is running*",
            f"node: `{container.kad.node_id}`",
            f"ports: kad={container.port} gossip={container.port + 1000} rpc={container.port + 2000}",
            f"peers: `{len(peers)}`",
            f"queued tasks: `{len(tasks)}`",
            f"records: `{len(all_rows)}` latest loaded; notes=`{len(notes)}` files=`{len(files)}`",
            f"metric schemes: `{len(snap)}`",
            f"arena api: `{arena_api_base}`",
            "",
            "Arena: `/arena <вопрос>` `/model` `/conv`",
            "Swarm: `/list notes`, `/list files`, `/rag Иван`",
        ]
        return "\n".join(lines)

    async def files_handler(_bot, _msg, _rest: str) -> str:
        rows = await repo.latest(table="files", n=10)
        if not rows:
            return "Файлов пока нет."
        lines = ["*Последние файлы:*"]
        for r in rows:
            name = r.data.get("filename", "?")
            size = r.data.get("size", 0)
            ref = r.data.get("ref", r.ref)
            sha = str(r.data.get("sha256", ""))[:12]
            lines.append(f"- `{name}` {size} bytes sha={sha}\n  `{ref}`")
        return "\n".join(lines)

    bot._handlers["/status"] = status_handler
    bot._handlers["/files"] = files_handler
    task = asyncio.create_task(bot.run(), name="TelegramBot")
    log.info(
        "Telegram bot started (allowlist=%s open_access=%s arena=%s)",
        sorted(allowed_chat_ids), open_access, arena_api_base,
    )
    return bot, task


async def amain() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "/etc/octopus/config.yaml"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    bootstrap = sys.argv[3] if len(sys.argv) > 3 else None

    cfg = load_config(config_path)
    container = AppContainer.from_config(cfg, port=port, bootstrap=bootstrap)
    runtime = AppRuntime(container)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    bot = None
    bot_task = None
    await runtime.start()
    try:
        if not os.environ.get("OCTOPUS_NO_BOT"):
            bot, bot_task = await _build_bot(container)
        await stop_event.wait()
    finally:
        if bot is not None:
            bot.stop()
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
        await runtime.stop()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()