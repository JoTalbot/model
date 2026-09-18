"""
swarm/network/rpc.py  (patched: межнодовая авторизация)
────────────────────────────────────────────────────────
Изменения относительно оригинала
  • RPCServer._handle_connection → верифицирует auth-блок через AuthVerifier
  • RPCClient.call              → добавляет auth-блок через AuthSigner
  • Оба объекта опциональны: если не переданы, поведение идентично оригиналу.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import msgpack

from swarm.network.auth import AuthSigner, AuthVerifier

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Coroutine[Any, Any, dict]]

# Контекстная переменная: адрес пира текущего RPC-запроса (host:port | )
rpc_peer_address: contextvars.ContextVar[str] = contextvars.ContextVar(
    "rpc_peer_address", default=""
)


class RPCServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        *,
        verifier: AuthVerifier | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._handlers: dict[str, Handler] = {}
        self._server: asyncio.Server | None = None
        self._verifier = verifier

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        logger.info("RPC server listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername", ("?", 0))
        _peer_token = rpc_peer_address.set(f"{peer[0]}:{peer[1]}")
        try:
            length_bytes = await reader.readexactly(4)
            length = int.from_bytes(length_bytes, "big")
            data = await reader.readexactly(length)
            request = msgpack.unpackb(data, raw=False)

            # ── Авторизация ─────────────────────────────────────────────────
            if self._verifier is not None:
                ok, reason = self._verifier.verify(request)
                if not ok:
                    logger.warning(
                        "RPC auth failed from %s:%s — %s", peer[0], peer[1], reason
                    )
                    response = {
                        "request_id": request.get("request_id", ""),
                        "error": f"Unauthorized: {reason}",
                    }
                    resp_data = msgpack.packb(response, use_bin_type=True)
                    writer.write(len(resp_data).to_bytes(4, "big"))
                    writer.write(resp_data)
                    await writer.drain()
                    return

            # ── Диспетчеризация ─────────────────────────────────────────────
            method     = request.get("method", "")
            params     = request.get("params", {})
            request_id = request.get("request_id", "")

            handler = self._handlers.get(method)
            if handler:
                result   = await handler(params)
                response = {"request_id": request_id, "result": result}
            else:
                response = {
                    "request_id": request_id,
                    "error": f"Unknown method: {method}",
                }

            resp_data = msgpack.packb(response, use_bin_type=True)
            writer.write(len(resp_data).to_bytes(4, "big"))
            writer.write(resp_data)
            await writer.drain()

        except Exception as exc:
            logger.error("RPC handler error from %s:%s — %s", peer[0], peer[1], exc)
        finally:
            rpc_peer_address.reset(_peer_token)
            writer.close()
            await writer.wait_closed()


class RPCClient:
    """
    Клиент для RPC-вызовов к другим узлам.

    Опциональный ``proxy`` (SOCKS5) маршрутизирует TCP-соединение через
    Tor / SOCKS-прокси. Требуется ``python-socks[asyncio]``.

    Опциональный ``signer`` добавляет auth-блок к каждому запросу.
    """

    def __init__(
        self,
        *,
        proxy: str | None = None,
        signer: AuthSigner | None = None,
    ) -> None:
        self._proxy  = proxy
        self._signer = signer

    # ── Подключение ──────────────────────────────────────────────────────────

    async def _open_connection(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._proxy and self._proxy.startswith(
            ("socks5://", "socks4://", "socks5h://")
        ):
            return await self._open_via_socks(host, port)
        return await asyncio.open_connection(host, port)

    async def _open_via_socks(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            from python_socks.async_.asyncio import Proxy

            proxy = Proxy.from_url(self._proxy)
            sock  = await proxy.connect(dest_host=host, dest_port=port)

            reader   = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            loop     = asyncio.get_running_loop()
            transport, _ = await loop.create_connection(lambda: protocol, sock=sock)
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            return reader, writer
        except ImportError:
            logger.warning(
                "python-socks not installed; falling back to direct connection. "
                "Install with: pip install python-socks[asyncio]"
            )
            return await asyncio.open_connection(host, port)

    # ── Вызов ────────────────────────────────────────────────────────────────

    async def call(
        self, host: str, port: int, method: str, params: dict
    ) -> dict:
        reader, writer = await self._open_connection(host, port)
        try:
            request: dict[str, Any] = {
                "method":     method,
                "params":     params,
                "request_id": str(uuid.uuid4()),
            }

            # ── Подписываем запрос ───────────────────────────────────────────
            if self._signer is not None:
                request = self._signer.sign_envelope(request)

            data = msgpack.packb(request, use_bin_type=True)
            writer.write(len(data).to_bytes(4, "big"))
            writer.write(data)
            await writer.drain()

            length_bytes = await reader.readexactly(4)
            length       = int.from_bytes(length_bytes, "big")
            resp_data    = await reader.readexactly(length)
            response     = msgpack.unpackb(resp_data, raw=False)
            result       = response.get("result")
            return result if result is not None else response
        finally:
            writer.close()
            await writer.wait_closed()

    async def close(self) -> None:
        pass
