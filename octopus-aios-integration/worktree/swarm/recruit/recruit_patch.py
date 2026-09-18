"""
swarm/recruit/recruit_patch.py
───────────────────────────────
Интеграция Recruiter + RecruitHandler в AppContainer / AppRuntime.

Подключение в swarm/runtime.py
───────────────────────────────
В AppContainer.from_config (в конце, перед return):
    from swarm.recruit.recruit_patch import patch_recruit
    patch_recruit(container, cfg)

В AppRuntime.start (после rpc_server.start):
    from swarm.recruit.recruit_patch import runtime_recruit_start
    await runtime_recruit_start(self)

В AppRuntime.stop (перед kad.stop):
    from swarm.recruit.recruit_patch import runtime_recruit_stop
    await runtime_recruit_stop(self)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def patch_recruit(container, cfg: dict) -> None:
    """
    Создать Recruiter и RecruitHandler и сохранить в контейнере.
    Вызывать из AppContainer.from_config.
    """
    from swarm.recruit.recruiter import RecruitHandler, Recruiter, SourcePacker

    recruit_cfg = cfg.get("recruit", {})
    if not recruit_cfg.get("enabled", False):
        container.recruiter       = None
        container.recruit_handler = None
        return

    secret      = (
        os.environ.get("SWARM_SECRET")
        or recruit_cfg.get("secret", "")
        or cfg.get("auth", {}).get("shared_secret", "")
    )
    advertise   = str((cfg.get("node") or {}).get("advertise_host", "127.0.0.1"))
    port        = container.port
    rpc_port    = port + 2000
    interval    = float(recruit_cfg.get("broadcast_interval_seconds", 60))
    max_recruits = int(recruit_cfg.get("max_recruits", 10))
    max_children = int(recruit_cfg.get("max_children", 4))
    spawn_dir   = recruit_cfg.get("spawn_dir", "/tmp/swarm_nodes")
    spawn_interval = float(recruit_cfg.get("spawn_interval_seconds", 30))
    role        = recruit_cfg.get("role", "both")   # "recruiter" | "candidate" | "both"
    # Child-ноды (запущенные через RECRUIT) не должны ни вербовать, ни плодить внуков.
    # Они уже являются детьми — рекрутинг полностью отключается.
    if os.environ.get("SWARM_SPAWNED") or os.environ.get("OCTOPUS_PARENT_PUBKEY"):
        container.recruiter       = None
        container.recruit_handler = None
        logger.info("Recruit: полностью отключён (child-нода — нет вербовки и нет спавна)")
        return

    node_id = container.kad.node_id or "unknown"

    # Recruiter (вербовщик)
    recruiter = None
    if role in ("recruiter", "both"):
        recruiter = Recruiter(
            node_id=node_id,
            host=advertise,
            rpc_port=rpc_port,
            gossip=container.gossip,
            secret=secret,
            interval=interval,
            max_recruits=max_recruits,
            packer=SourcePacker(),
        )

    # RecruitHandler (кандидат)
    handler = None
    if role in ("candidate", "both"):
        handler = RecruitHandler(
            node_id=node_id,
            rpc_client=container.rpc_client,
            secret=secret,
            base_port=port,
            max_children=max_children,
            spawn_interval=spawn_interval,
            spawn_dir=spawn_dir,
            bus=container.bus,
            enabled=True,
        )

    container.recruiter       = recruiter
    container.recruit_handler = handler

    logger.info(
        "Recruit patch applied: role=%s, interval=%.0fs, max_recruits=%d",
        role, interval, max_recruits,
    )


async def runtime_recruit_start(runtime) -> None:
    """
    Запустить рекрутинг. Вызывать из AppRuntime.start
    после await c.rpc_server.start().
    """
    c = runtime.container

    recruiter: "Recruiter | None" = getattr(c, "recruiter", None)
    handler:   "RecruitHandler | None" = getattr(c, "recruit_handler", None)

    if recruiter is None and handler is None:
        return

    # Обновляем node_id (он мог измениться после kad.start)
    nid = c.kad.node_id or "unknown"
    if recruiter:
        recruiter.node_id = nid
        recruiter.register_rpc(c.rpc_server)
        recruiter.start()

    if handler:
        handler.node_id = nid
        # Вшиваем в gossip unified handler
        _patch_gossip_handler(c, handler)

    # Регистрируем RPC-методы мониторинга
    _register_recruit_rpc(c)


async def runtime_recruit_stop(runtime) -> None:
    """
    Остановить рекрутинг. Вызывать из AppRuntime.stop.
    """
    c = runtime.container
    recruiter = getattr(c, "recruiter", None)
    handler   = getattr(c, "recruit_handler", None)

    if recruiter:
        await recruiter.stop()
    if handler:
        await handler.stop_children()


# ── Внутренние хелперы ────────────────────────────────────────────────────────

def _patch_gossip_handler(container, handler: "RecruitHandler") -> None:
    """Добавить handle_gossip к существующему unified_gossip_handler."""
    original = container.gossip._on_message

    async def patched_handler(msg):
        if original:
            await original(msg)
        await handler.handle_gossip(msg)

    container.gossip._on_message = patched_handler
    logger.debug("RecruitHandler: встроен в gossip_handler")


def _register_recruit_rpc(container) -> None:
    """RPC-методы для мониторинга рекрутинга через CLI / веб-интерфейс."""
    recruiter = getattr(container, "recruiter", None)
    handler   = getattr(container, "recruit_handler", None)

    async def recruit_stats_handler(params: dict) -> dict:
        return {
            "ok":        True,
            "recruiter": recruiter.stats() if recruiter else None,
            "handler":   handler.stats()   if handler   else None,
        }

    async def recruit_enable_handler(params: dict) -> dict:
        if handler:
            handler.enabled = bool(params.get("enabled", True))
        return {"ok": True, "enabled": handler.enabled if handler else False}

    async def recruit_broadcast_now_handler(params: dict) -> dict:
        """Немедленная рассылка RECRUIT (для тестирования)."""
        if not recruiter:
            return {"ok": False, "reason": "recruiter not enabled"}
        from swarm.network.gossip import GossipMessage
        import time
        msg = GossipMessage(
            msg_type="RECRUIT",
            payload={
                "recruiter_id":  recruiter.node_id,
                "rpc_host":      recruiter.host,
                "rpc_port":      recruiter.rpc_port,
                "token":         recruiter._token,
                "digest":        recruiter._digest,
                "max_children":  4,
                "ts":            time.time(),
            },
        )
        await container.gossip.inject(msg)
        return {"ok": True, "digest": recruiter._digest[:12]}

    container.rpc_server.register("recruit_stats",         recruit_stats_handler)
    container.rpc_server.register("recruit_enable",        recruit_enable_handler)
    container.rpc_server.register("recruit_broadcast_now", recruit_broadcast_now_handler)
