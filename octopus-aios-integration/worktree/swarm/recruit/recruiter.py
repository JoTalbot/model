"""
swarm/recruit/recruiter.py
───────────────────────────
Gossip-рекрутинг: нода рассылает приглашения в рой.
Пир-кандидат получает RECRUIT-сообщение, скачивает пакет
через RPC и запускает себя как новую ноду.

Схема
─────

  Нода-вербовщик (Recruiter)
  ──────────────────────────
  1. Упаковывает себя в zip-архив (только исходники, без .git)
  2. Сохраняет архив во временный слот (RPC-доступный)
  3. Периодически рассылает через Gossip:
       { type: RECRUIT, rpc_host, rpc_port, token, slots: [slot_id] }
  4. При RPC-запросе "recruit_fetch" отдаёт архив

  Нода-кандидат (RecruitHandler)
  ───────────────────────────────
  1. Получает RECRUIT через Gossip-обработчик
  2. Проверяет токен (HMAC из shared_secret)
  3. Скачивает zip через RPC "recruit_fetch"
  4. Распаковывает в изолированную директорию
  5. Запускает subprocess с новым портом
  6. Сообщает о себе через handshake

Безопасность
────────────
  • HMAC-токен (RECRUIT_SECRET в config или env)
  • Архив проверяется по SHA-256 (digest передаётся в RECRUIT)
  • Новая нода запускается с --bootstrap → к вербовщику
  • Лимит спавна: не более MAX_CHILDREN нод с одной машины
  • Cooldown: не спавним чаще MIN_SPAWN_INTERVAL_SEC
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Константы ──────────────────────────────────────────────────────────────
MAX_CHILDREN         = 4       # максимум порождённых нод с одной машины
MIN_SPAWN_INTERVAL_SEC = 30    # минимальный интервал между спавнами
RECRUIT_COOLDOWN_SEC   = 60    # игнорировать RECRUIT от одного вербовщика N сек
ARCHIVE_MAX_BYTES      = 50 * 1024 * 1024  # 50 MB — защита от bomb


# ══════════════════════════════════════════════════════════════════════════════
# Событие рекрутинга
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RecruitBroadcast:
    """Событие: нода объявила рекрутинг."""
    recruiter_id:  str
    recruiter_addr: str  # host:rpc_port


@dataclass(frozen=True)
class NodeSpawned:
    """Событие: порождена новая нода."""
    port:     int
    pid:      int
    base_dir: str


# ══════════════════════════════════════════════════════════════════════════════
# Упаковщик архива
# ══════════════════════════════════════════════════════════════════════════════

class SourcePacker:
    """
    Упаковывает исходный код ноды в zip-архив в памяти.

    Исключает: .git, __pycache__, *.pyc, node_modules,
               .venv, .swarm_keys, .swarm_scratch, *.zip
    """

    EXCLUDE_DIRS  = {".git", "__pycache__", "node_modules", ".venv",
                     ".swarm_keys", ".swarm_scratch", ".arena"}
    EXCLUDE_EXTS  = {".pyc", ".pyo", ".zip", ".tar", ".gz", ".egg-info"}
    EXCLUDE_FILES = {".DS_Store", "Thumbs.db"}

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or self._detect_root()).resolve()

    def _detect_root(self) -> Path:
        """Найти корень проекта (где лежит node.py / swarm/)."""
        here = Path(__file__).resolve()
        for p in [here, *here.parents]:
            if (p / "node.py").exists() or (p / "swarm").is_dir():
                return p
        return Path.cwd()

    def pack(self) -> tuple[bytes, str]:
        """
        Упаковать исходники.
        Возвращает (zip_bytes, sha256_hex).
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in self._walk():
                arcname = path.relative_to(self.root)
                zf.write(path, arcname)

        data    = buf.getvalue()
        digest  = hashlib.sha256(data).hexdigest()
        logger.info(
            "SourcePacker: упаковано %d байт, sha256=%s...",
            len(data), digest[:12],
        )
        return data, digest

    def _walk(self):
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            # Исключить по директории
            parts = set(path.parts)
            if parts & {str(self.root / d) for d in self.EXCLUDE_DIRS}:
                continue
            if any(d in self.EXCLUDE_DIRS for d in path.parts):
                continue
            # Исключить по расширению
            if path.suffix in self.EXCLUDE_EXTS:
                continue
            # Исключить по имени файла
            if path.name in self.EXCLUDE_FILES:
                continue
            yield path


# ══════════════════════════════════════════════════════════════════════════════
# Recruiter — сторона вербовщика
# ══════════════════════════════════════════════════════════════════════════════

class Recruiter:
    """
    Рассылает RECRUIT через gossip и отдаёт архив по RPC.

    Использование:
        recruiter = Recruiter(node_keys=keys, gossip=gossip, secret="s3cr3t")
        recruiter.register_rpc(rpc_server)          # "recruit_fetch"
        asyncio.create_task(recruiter.broadcast_loop(host, rpc_port))
    """

    def __init__(
        self,
        *,
        node_id:    str,
        host:       str,
        rpc_port:   int,
        gossip,
        secret:     str = "",
        interval:   float = 60.0,   # как часто рассылать RECRUIT
        max_recruits: int = 10,     # всего нод набрать
        packer:     SourcePacker | None = None,
    ) -> None:
        self.node_id    = node_id
        self.host       = host
        self.rpc_port   = rpc_port
        self.gossip     = gossip
        self._secret    = secret.encode() if secret else b""
        self.interval   = interval
        self.max_recruits = max_recruits
        self._packer    = packer or SourcePacker()
        self._archive:  bytes = b""
        self._digest:   str   = ""
        self._token:    str   = ""
        self._recruited: int  = 0
        self._task:     asyncio.Task | None = None

    # ── Старт / стоп ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._pack_archive()
        self._task = asyncio.create_task(self._broadcast_loop())
        logger.info(
            "Recruiter started: %s:%d, interval=%.0fs",
            self.host, self.rpc_port, self.interval,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Архив ────────────────────────────────────────────────────────────────

    def _pack_archive(self) -> None:
        self._archive, self._digest = self._packer.pack()
        self._token = self._make_token()

    def _make_token(self) -> str:
        """HMAC-токен для верификации на стороне кандидата."""
        if not self._secret:
            return "open"
        payload = f"{self.node_id}:{self._digest}".encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    # ── RPC-обработчик "recruit_fetch" ───────────────────────────────────────

    def register_rpc(self, rpc_server) -> None:
        """Зарегистрировать обработчик на RPCServer."""
        rpc_server.register("recruit_fetch", self._handle_fetch)
        logger.debug("Recruiter: RPC 'recruit_fetch' зарегистрирован")

    async def _handle_fetch(self, params: dict) -> dict:
        """Отдать архив пиру-кандидату."""
        token = params.get("token", "")
        if self._secret and token != self._token:
            logger.warning("Recruit fetch: неверный токен от %s", params.get("peer_id"))
            return {"ok": False, "reason": "invalid_token"}

        if not self._archive:
            return {"ok": False, "reason": "archive_not_ready"}

        self._recruited += 1
        logger.info(
            "Recruit fetch: отправляем архив (%d байт) кандидату #%d",
            len(self._archive), self._recruited,
        )
        return {
            "ok":     True,
            "data":   list(self._archive),   # bytes → list[int] для msgpack
            "digest": self._digest,
            "node_id": self.node_id,
            "bootstrap": f"{self.host}:{self.rpc_port - 2000}",  # kad port
        }

    # ── Gossip-рассылка ──────────────────────────────────────────────────────

    async def _broadcast_loop(self) -> None:
        """Периодически рассылать RECRUIT через gossip."""
        from swarm.network.gossip import GossipMessage
        while True:
            if self._recruited < self.max_recruits:
                msg = GossipMessage(
                    msg_type="RECRUIT",
                    payload={
                        "recruiter_id":  self.node_id,
                        "rpc_host":      self.host,
                        "rpc_port":      self.rpc_port,
                        "token":         self._token,
                        "digest":        self._digest,
                        "max_children":  MAX_CHILDREN,
                        "ts":            time.time(),
                    },
                )
                await self.gossip.inject(msg)
                logger.debug("RECRUIT broadcast → %d пиров", len(self.gossip._peers))
            await asyncio.sleep(self.interval)

    def stats(self) -> dict:
        return {
            "recruited":    self._recruited,
            "max_recruits": self.max_recruits,
            "archive_size": len(self._archive),
            "digest":       self._digest[:12] + "..." if self._digest else "",
            "interval":     self.interval,
        }


# ══════════════════════════════════════════════════════════════════════════════
# RecruitHandler — сторона кандидата
# ══════════════════════════════════════════════════════════════════════════════

class RecruitHandler:
    """
    Обрабатывает входящий RECRUIT gossip-пакет:
      1. Верифицирует токен
      2. Скачивает архив через RPC
      3. Проверяет SHA-256
      4. Распаковывает в temp-директорию
      5. Запускает subprocess

    Один экземпляр на ноду. Передаётся в GossipProtocol как on_message
    (или вызывается из unified_gossip_handler).
    """

    def __init__(
        self,
        *,
        node_id:    str,
        rpc_client,
        secret:     str = "",
        base_port:  int = 8000,      # стартовый порт для детей
        max_children: int = MAX_CHILDREN,
        spawn_interval: float = MIN_SPAWN_INTERVAL_SEC,
        spawn_dir:  str | Path = "/tmp/swarm_nodes",
        bus=None,
        enabled:    bool = True,
    ) -> None:
        self.node_id        = node_id
        self.rpc_client     = rpc_client
        self._secret        = secret.encode() if secret else b""
        self.base_port      = base_port
        self.max_children   = max_children
        self.spawn_interval = spawn_interval
        self.spawn_dir      = Path(spawn_dir)
        self._bus           = bus
        self.enabled        = enabled

        self._children:  list[subprocess.Popen] = []
        self._last_spawn: float = 0.0
        # cooldown per recruiter_id
        self._seen_recruiters: dict[str, float] = {}

    # ── Gossip-обработчик ────────────────────────────────────────────────────

    async def handle_gossip(self, msg) -> None:
        """Вызывается из unified_gossip_handler."""
        if msg.msg_type != "RECRUIT":
            return
        if not self.enabled:
            return
        await self._process_recruit(msg.payload)

    # ── Основная логика ──────────────────────────────────────────────────────

    async def _process_recruit(self, payload: dict) -> None:
        recruiter_id = payload.get("recruiter_id", "")
        rpc_host     = payload.get("rpc_host", "")
        rpc_port     = int(payload.get("rpc_port", 0))
        token        = payload.get("token", "")
        digest       = payload.get("digest", "")
        ts           = float(payload.get("ts", 0))

        # Не рекрутировать самих себя
        if recruiter_id == self.node_id:
            return

        # Cooldown per recruiter
        now = time.time()
        last = self._seen_recruiters.get(recruiter_id, 0)
        if now - last < RECRUIT_COOLDOWN_SEC:
            return
        self._seen_recruiters[recruiter_id] = now

        # Timestamp check
        if abs(now - ts) > 120:
            logger.debug("RECRUIT: устаревший пакет от %s, пропускаем", recruiter_id)
            return

        # Лимиты
        self._reap_dead_children()
        if len(self._children) >= self.max_children:
            logger.debug("RECRUIT: достигнут лимит %d нод, пропускаем", self.max_children)
            return
        if now - self._last_spawn < self.spawn_interval:
            logger.debug("RECRUIT: cooldown, следующий спавн через %.0fs",
                         self.spawn_interval - (now - self._last_spawn))
            return

        # Верификация токена
        if self._secret:
            expected = hmac.new(
                self._secret,
                f"{recruiter_id}:{digest}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, token):
                logger.warning("RECRUIT: неверный токен от %s", recruiter_id)
                return

        logger.info("RECRUIT: принимаем от %s @ %s:%d", recruiter_id, rpc_host, rpc_port)

        # Скачать архив
        archive, bootstrap = await self._fetch_archive(rpc_host, rpc_port, token)
        if not archive:
            return

        # Проверить digest
        actual = hashlib.sha256(archive).hexdigest()
        if actual != digest:
            logger.error("RECRUIT: digest mismatch! ожидал %s, получил %s",
                         digest[:12], actual[:12])
            return

        # Распаковать и запустить
        port = self._pick_port()
        if not port:
            logger.warning("RECRUIT: нет свободных портов")
            return

        node_dir = self.spawn_dir / f"node_{port}"
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._unpack, archive, node_dir
            )
            proc = await self._spawn(node_dir, port, bootstrap or f"{rpc_host}:{rpc_port - 2000}")
            self._children.append(proc)
            self._last_spawn = time.time()
            logger.info("✅ RECRUIT: нода запущена на порту %d (pid=%d)", port, proc.pid)

            if self._bus:
                await self._bus.publish(NodeSpawned(
                    port=port, pid=proc.pid, base_dir=str(node_dir)
                ))
        except Exception as exc:
            logger.error("RECRUIT: ошибка запуска ноды: %s", exc)
            shutil.rmtree(node_dir, ignore_errors=True)

    # ── RPC-скачивание ────────────────────────────────────────────────────────

    async def _fetch_archive(
        self, host: str, port: int, token: str
    ) -> tuple[bytes, str]:
        try:
            res = await asyncio.wait_for(
                self.rpc_client.call(host, port, "recruit_fetch", {
                    "peer_id": self.node_id,
                    "token":   token,
                }),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("RECRUIT fetch timeout от %s:%d", host, port)
            return b"", ""
        except Exception as exc:
            logger.warning("RECRUIT fetch error: %s", exc)
            return b"", ""

        if not res or not res.get("ok"):
            logger.warning("RECRUIT fetch отклонён: %s", (res or {}).get("reason"))
            return b"", ""

        raw = res.get("data", [])
        archive = bytes(raw) if isinstance(raw, list) else raw
        if len(archive) > ARCHIVE_MAX_BYTES:
            logger.error("RECRUIT: архив слишком большой (%d байт), отклоняем", len(archive))
            return b"", ""

        bootstrap = res.get("bootstrap", "")
        logger.info("RECRUIT: получен архив %d байт от %s:%d", len(archive), host, port)
        return archive, bootstrap

    # ── Распаковка ────────────────────────────────────────────────────────────

    def _unpack(self, archive: bytes, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            # Защита от path traversal
            for member in zf.namelist():
                if ".." in member or member.startswith("/"):
                    raise ValueError(f"Небезопасный путь в архиве: {member!r}")
            zf.extractall(dest)
        logger.debug("RECRUIT: распакован в %s", dest)

    # ── Запуск ────────────────────────────────────────────────────────────────

    async def _spawn(
        self, node_dir: Path, port: int, bootstrap: str
    ) -> subprocess.Popen:
        """Запустить новую ноду в subprocess."""
        python = sys.executable
        entry  = node_dir / "node.py"
        if not entry.exists():
            # Попробовать найти entry point
            candidates = list(node_dir.glob("node.py")) + list(node_dir.rglob("node.py"))
            if not candidates:
                raise FileNotFoundError(f"node.py не найден в {node_dir}")
            entry = candidates[0]

        cmd = [
            python, str(entry),
            "start",
            "--port", str(port),
            "--bootstrap", bootstrap,
        ]

        env = os.environ.copy()
        env["SWARM_SPAWNED"] = "1"
        env["SWARM_PARENT"]  = self.node_id

        proc = subprocess.Popen(
            cmd,
            cwd=str(node_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,   # не убивается при смерти родителя
        )
        return proc

    # ── Утилиты ──────────────────────────────────────────────────────────────

    def _pick_port(self) -> int | None:
        """Выбрать свободный порт для новой ноды."""
        import socket
        for port in range(self.base_port + 100, self.base_port + 100 + 50):
            with socket.socket() as s:
                try:
                    s.bind(("", port))
                    return port
                except OSError:
                    continue
        return None

    def _reap_dead_children(self) -> None:
        """Убрать завершённые процессы из списка."""
        self._children = [p for p in self._children if p.poll() is None]

    def stats(self) -> dict:
        self._reap_dead_children()
        return {
            "active_children": len(self._children),
            "max_children":    self.max_children,
            "last_spawn":      self._last_spawn,
            "enabled":         self.enabled,
            "seen_recruiters": len(self._seen_recruiters),
        }

    async def stop_children(self) -> None:
        """Остановить все порождённые ноды."""
        for proc in self._children:
            try:
                proc.terminate()
            except Exception:
                pass
        self._children.clear()
