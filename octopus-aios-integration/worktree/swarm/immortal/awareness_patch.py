"""
swarm/immortal/awareness_patch.py
───────────────────────────────────
Интеграция NodeSelf в AppContainer / AppRuntime.

Подключение в swarm/runtime.py
────────────────────────────────
В AppContainer.from_config (перед return):
    from swarm.immortal.awareness_patch import patch_awareness
    patch_awareness(container, cfg)

В AppRuntime.start (после gossip.start):
    from swarm.immortal.awareness_patch import runtime_awareness_start
    await runtime_awareness_start(self)

В AppRuntime.stop:
    from swarm.immortal.awareness_patch import runtime_awareness_stop
    await runtime_awareness_stop(self)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def patch_awareness(container, cfg: dict) -> None:
    """
    Создать NodeSelf и подключить к AwarenessPropagation.
    Вызывать из AppContainer.from_config.
    """
    from swarm.immortal.node_self import NodeRole, NodeSelf, SkillDescriptor

    awareness_cfg = cfg.get("awareness", {})
    if not awareness_cfg.get("enabled", True):   # включён по умолчанию
        container.node_self = None
        return

    role_str = awareness_cfg.get("role", "hybrid")
    try:
        role = NodeRole(role_str)
    except ValueError:
        role = NodeRole.HYBRID

    interval    = float(awareness_cfg.get("broadcast_interval_seconds", 30))
    spawned_by  = os.environ.get("SWARM_PARENT", "")

    node_id = container.kad.node_id or "unknown"
    node_self = NodeSelf(
        node_id=node_id,
        role=role,
        spawned_by=spawned_by,
        broadcast_interval=interval,
    )

    # Регистрируем базовые навыки из конфига
    skills_cfg = awareness_cfg.get("skills", [])
    for sk in skills_cfg:
        if isinstance(sk, str):
            node_self.register_skill(SkillDescriptor(name=sk))
        elif isinstance(sk, dict):
            node_self.register_skill(SkillDescriptor(**sk))

    # Авто-навыки по наличию компонентов
    _auto_register_skills(node_self, container, cfg)

    # Подключить к существующему AwarenessPropagation если есть
    try:
        from swarm.immortal.awareness import AwarenessPropagation
        from swarm.immortal.vector_clock import VectorClock
        vc  = VectorClock(node_id=node_id)
        ap  = AwarenessPropagation(node_id=node_id, clock=vc)
        node_self.attach_awareness(ap)
        container.awareness_propagation = ap
    except ImportError:
        container.awareness_propagation = None

    container.node_self = node_self

    logger.info(
        "Awareness patch applied: role=%s, skills=%s, interval=%.0fs",
        role.value,
        [s.name for s in node_self._skills],
        interval,
    )


def _auto_register_skills(node_self, container, cfg: dict) -> None:
    """Автоматически регистрировать навыки по наличию компонентов."""
    from swarm.immortal.node_self import SkillDescriptor

    # Заметки / память
    if getattr(container, "agent", None) and getattr(container.agent, "memory_port", None):
        node_self.register_skill(SkillDescriptor(
            name="note_search",
            description="Поиск по локальным заметкам (RAG)",
        ))
        node_self.register_skill(SkillDescriptor(
            name="memory_store",
            description="Хранение данных в распределённой памяти",
        ))

    # LLM
    if getattr(container, "llm", None):
        models = (cfg.get("llm") or {}).get("models", [])
        local  = (cfg.get("llm") or {}).get("local", {})
        if local.get("enabled"):
            node_self.register_skill(SkillDescriptor(
                name="local_llm",
                description=f"Локальная LLM: {local.get('models', ['?'])[0]}",
            ))
        if models:
            node_self.register_skill(SkillDescriptor(
                name="cloud_llm",
                description=f"Облачная LLM: {models[0]}",
            ))

    # Парсер
    if (cfg.get("agents") or []):
        for a in cfg["agents"]:
            if a.get("name") == "parser":
                node_self.register_skill(SkillDescriptor(
                    name="web_parser",
                    description="Парсинг веб-страниц и структурирование данных",
                ))

    # Рекрутинг
    if (cfg.get("recruit") or {}).get("enabled"):
        role = (cfg.get("recruit") or {}).get("role", "both")
        if role in ("recruiter", "both"):
            node_self.register_skill(SkillDescriptor(name="recruiter"))
        if role in ("candidate", "both"):
            node_self.register_skill(SkillDescriptor(name="candidate"))

    # Задачи
    node_self.register_skill(SkillDescriptor(
        name="task_execution",
        description="Выполнение задач роя",
        capacity=4,
    ))


async def runtime_awareness_start(runtime) -> None:
    """
    Запустить NodeSelf. Вызывать из AppRuntime.start
    после await c.gossip.start().
    """
    c = runtime.container
    ns: "NodeSelf | None" = getattr(c, "node_self", None)
    if ns is None:
        return

    # Обновляем node_id после kad.start
    nid = c.kad.node_id or "unknown"
    ns.node_id = nid
    if getattr(c, "awareness_propagation", None):
        c.awareness_propagation.node_id = nid

    # Встраиваем handle_gossip в unified_gossip_handler
    _patch_gossip_handler(c, ns)

    # Регистрируем RPC
    _register_awareness_rpc(c, ns)

    # Запускаем broadcast loop
    ns.start(c.gossip)

    # Запускаем периодический сбор нагрузки
    import asyncio
    asyncio.create_task(_load_collector_loop(c, ns))

    # ── Awareness: синхронизируем gossip._peers из PeerRegistry ──────────────
    # После handshake пиры есть в registry, но могут ещё не быть в gossip._peers.
    # Запускаем цикл подписки на NODE_AWARENESS от зарегистрированных пиров.
    asyncio.create_task(_awareness_gossip_sync_loop(c, ns))

    # Немедленный broadcast чтобы сообщить о себе уже подключённым пирам
    asyncio.create_task(_delayed_first_broadcast(ns, delay=3.0))

    logger.info("NodeSelf started for node %s", nid)


async def runtime_awareness_stop(runtime) -> None:
    c = runtime.container
    ns = getattr(c, "node_self", None)
    if ns:
        await ns.stop()


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _patch_gossip_handler(container, ns) -> None:
    original = container.gossip._on_message

    async def patched(msg):
        if original:
            await original(msg)
        await ns.handle_gossip(msg)

    container.gossip._on_message = patched


def _register_awareness_rpc(container, ns) -> None:
    """RPC-методы для опроса awareness."""

    async def node_self_handler(params: dict) -> dict:
        return {"ok": True, **ns.stats()}

    async def swarm_map_handler(params: dict) -> dict:
        skill = params.get("skill")
        if skill:
            nodes = ns.find_nodes_with_skill(skill)
        else:
            nodes = list(ns.swarm_map().values())
        return {
            "ok":    True,
            "count": len(nodes),
            "nodes": [n.to_payload() for n in nodes],
        }

    async def swarm_healthiest_handler(params: dict) -> dict:
        n     = int(params.get("n", 3))
        nodes = ns.find_healthiest(n)
        return {"ok": True, "nodes": [nd.to_payload() for nd in nodes]}

    async def awareness_broadcast_handler(params: dict) -> dict:
        await ns.broadcast()
        return {"ok": True}

    async def swarm_prune_handler(params: dict) -> dict:
        ttl    = float(params.get("ttl", 120))
        pruned = ns.prune_stale(ttl)
        return {"ok": True, "pruned": pruned}

    container.rpc_server.register("node_self",           node_self_handler)
    container.rpc_server.register("swarm_map",           swarm_map_handler)
    container.rpc_server.register("swarm_healthiest",    swarm_healthiest_handler)
    container.rpc_server.register("awareness_broadcast", awareness_broadcast_handler)
    container.rpc_server.register("swarm_prune",         swarm_prune_handler)


async def _delayed_first_broadcast(ns, delay: float = 3.0) -> None:
    """Broadcast сразу после старта чтобы пиры узнали о нас."""
    import asyncio
    await asyncio.sleep(delay)
    try:
        await ns.broadcast()
        logger.info("NodeSelf: первый awareness broadcast отправлен")
    except Exception as exc:
        logger.warning("NodeSelf: ошибка первого broadcast: %s", exc)


async def _awareness_gossip_sync_loop(container, ns) -> None:
    """
    Периодически проверяет PeerRegistry и добавляет пиров в gossip._peers.
    Также делает broadcast awareness после появления нового пира.
    """
    import asyncio
    gossip = container.gossip
    registry = getattr(container, "peer_registry", None)
    if registry is None:
        logger.warning("NodeSelf awareness sync: peer_registry не найден")
        return

    known_peers: set[str] = set()  # node_id уже добавленных пиров

    while True:
        try:
            await asyncio.sleep(10)
            current_peers = {p.node_id for p in registry.all_peers()}
            new_peers = current_peers - known_peers
            if new_peers:
                for peer_info in registry.all_peers():
                    if peer_info.node_id not in new_peers:
                        continue
                    addr = peer_info.address
                    if not addr:
                        continue
                    try:
                        host, rpc_port_s = addr.rsplit(":", 1)
                        rpc_port = int(rpc_port_s)
                        # gossip порт: по соглашению rpc_port - 1000
                        gossip_port = rpc_port - 1000
                        gossip.add_peer(host, gossip_port)
                        logger.info(
                            "NodeSelf awareness: gossip peer добавлен %s:%d (node_id=%s)",
                            host, gossip_port, peer_info.node_id
                        )
                    except (ValueError, IndexError) as exc:
                        logger.warning("NodeSelf awareness: bad peer addr %s — %s", addr, exc)
                known_peers = current_peers
                # Broadcast после появления нового пира
                await ns.broadcast()
                logger.info("NodeSelf: awareness broadcast после появления %d новых пиров", len(new_peers))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("NodeSelf awareness sync error: %s", exc)


async def _load_collector_loop(container, ns) -> None:
    """Каждые 10 секунд собирает реальную нагрузку и обновляет NodeSelf."""
    import asyncio
    from swarm.immortal.node_self import LoadSnapshot

    while True:
        try:
            await asyncio.sleep(10)
            agent   = getattr(container, "agent", None)
            gossip  = container.gossip

            load = LoadSnapshot(
                tasks_pending  = agent.task_queue.qsize() if agent else 0,
                tasks_running  = sum(
                    1 for t in (agent.pool.values() if agent else [])
                    if getattr(t, "status", None) and t.status.value == "running"
                ),
                tasks_done     = sum(
                    1 for t in (agent.pool.values() if agent else [])
                    if getattr(t, "status", None) and t.status.value == "done"
                ),
                gossip_rx      = gossip.total_received,
                gossip_tx      = gossip.total_sent,
                peers_count    = len(gossip._peers),
            )

            # Попробовать получить системные метрики (опционально)
            try:
                import psutil
                load.cpu_percent = psutil.cpu_percent(interval=None)
                load.ram_mb      = psutil.virtual_memory().used / 1024 / 1024
            except ImportError:
                pass

            ns.observe_load(load)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Load collector error: %s", exc)
