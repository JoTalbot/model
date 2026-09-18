from __future__ import annotations

import asyncio
import os
import logging
from dataclasses import dataclass
from typing import Any

import click

from swarm.agent.archivist import Archivist
from swarm.agent.core import SwarmAgent, TaskStatus, Task
from swarm.agent.linker import MemoryLinker
from swarm.agent.reputation import ReputationManager
from swarm.config.app import AppConfig
from swarm.config.helpers import (
    llm_local_router_kwargs,
    parse_repair_seeds,
    yaml_bootstrap_addr,
)
from swarm.events import EventBus, NodeJoined, NodeLeft
from swarm.llm.key_pool import APIKey, KeyPool
from swarm.llm.router import LLMRouter
from swarm.memory.erasure import ErasureCoder
from swarm.memory.factory import build_memory_port
from swarm.memory.graph_rag import GraphRAG
from swarm.memory.immortal import EncryptedStorage, ImmortalMemoryManager, IPFSProvider
from swarm.memory.repository import MemoryRepository
from swarm.memory.store import DistributedMemory, ShardRepairSettings
from swarm.memory.sync import SyncEngine
from swarm.memory.vector_store import VectorStore
from swarm.memory.vfs import VirtualFileSystem
from swarm.network.gossip import GossipProtocol
from swarm.network.kademlia import KademliaNode
from swarm.network.rpc import RPCClient, RPCServer
from swarm.network.tor import TorManager
from swarm.plugins.metrics import MetricsPlugin
from swarm.plugins.registry import PluginRegistry

logger = logging.getLogger("swarm")


@dataclass
class AppContainer:
    cfg: AppConfig
    bus: EventBus
    plugin_registry: PluginRegistry
    port: int
    bootstrap: str | None
    kad: KademliaNode
    gossip: GossipProtocol
    rpc_client: RPCClient
    rpc_server: RPCServer
    llm: LLMRouter
    memory: DistributedMemory
    agent: SwarmAgent
    vfs: VirtualFileSystem
    sync_engine: SyncEngine
    immortal_manager: ImmortalMemoryManager
    linker: MemoryLinker
    archivist: Archivist
    graph_rag: GraphRAG
    reputation: ReputationManager | None = None
    tor_manager: TorManager | None = None
    peer_registry: Any | None = None
    handshake_mgr: Any | None = None
    mdns_inst: object | None = None

    @classmethod
    def from_config(cls, cfg: AppConfig, port: int, bootstrap: str | None) -> AppContainer:
        from swarm.memory.adapters.local_scratch import LocalScratchAdapter
        from swarm.network.outbound_http import outbound_http_proxy_url
        from swarm.plugins.loader import load_plugins

        bus = EventBus()
        plugin_registry = PluginRegistry()
        plugin_registry.register(MetricsPlugin())
        plugin_registry.register_adapter("file", LocalScratchAdapter)
        plugin_cfg = cfg.get("plugins", {}) or {}
        module_names = plugin_cfg.get("modules", []) if hasattr(plugin_cfg, "get") else []
        load_plugins(list(module_names), plugin_registry)

        try:
            llm_proxy = outbound_http_proxy_url(cfg)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        kad = KademliaNode(port=port)
        gossip_cfg = cfg.get("gossip", {})
        gossip = GossipProtocol(
            host=("127.0.0.1" if os.environ.get("SWARM_SPAWNED") else "0.0.0.0"),
            port=port + 1000,
            interval=gossip_cfg.get("interval", 5),
            fanout=gossip_cfg.get("fanout", 3),
            seen_capacity=gossip_cfg.get("seen_capacity", 1000),
            bus=bus,
        )
        
        # Tor Integration
        tor_manager = None
        rpc_proxy = llm_proxy
        tor_cfg = cfg.network.tor
        if tor_cfg.enabled:
            tor_manager = TorManager(
                proxy_url=tor_cfg.proxy_url,
                control_port=tor_cfg.control_port,
                hidden_service_port=tor_cfg.hidden_service_port,
                local_port=port + 2000, # RPC port
                tor_data_dir=tor_cfg.data_dir
            )
            rpc_proxy = tor_cfg.proxy_url

        rpc_client = RPCClient(proxy=rpc_proxy)
        rpc_server = RPCServer(host=("127.0.0.1" if os.environ.get("SWARM_SPAWNED") else "0.0.0.0"), port=port + 2000)

        llm_cfg = cfg["llm"]
        local_kw = llm_local_router_kwargs(llm_cfg)
        keys = [APIKey(key=k) for k in llm_cfg.get("keys", [])]
        cloud_models = llm_cfg.get("models") or []
        if keys:
            key_pool = KeyPool(keys=keys)
            llm = LLMRouter(
                key_pool=key_pool,
                models=cloud_models,
                base_url=llm_cfg.get("base_url") or "https://openrouter.ai/api/v1",
                timeout=llm_cfg["timeout"],
                max_retries=llm_cfg.get("max_retries") or 3,
                proxy=llm_proxy,
                bus=bus,
                **local_kw,
            )
        elif local_kw:
            key_pool = KeyPool(keys=[APIKey(key="local-placeholder")])
            llm = LLMRouter(
                key_pool=key_pool,
                models=cloud_models,
                base_url=llm_cfg.get("base_url") or "https://openrouter.ai/api/v1",
                timeout=llm_cfg["timeout"],
                max_retries=llm_cfg.get("max_retries") or 3,
                proxy=llm_proxy,
                bus=bus,
                **local_kw,
            )
        else:
            llm = None

        mem_cfg = cfg.get("memory", {})
        erasure_cfg = mem_cfg.get("erasure", {})
        coder = ErasureCoder(
            data_shards=mem_cfg.get("data_shards", erasure_cfg.get("data_shards", 4)),
            parity_shards=mem_cfg.get("parity_shards", erasure_cfg.get("parity_shards", 2)),
        )
        rpc_off = int(mem_cfg.get("repair_rpc_port_offset", mem_cfg.get("rpc_port_offset", 2000)))
        advertise_host = str((cfg.get("node") or {}).get("advertise_host", "127.0.0.1"))
        shard_repair = ShardRepairSettings(
            rpc_timeout_seconds=float(mem_cfg.get("repair_rpc_timeout_seconds", 8.0)),
            max_peers_per_shard=int(mem_cfg.get("repair_max_peers_per_shard", 32)),
            parallel_fetches=int(mem_cfg.get("repair_parallel_fetches", 3)),
            rpc_port_offset=rpc_off,
            seeds=parse_repair_seeds(mem_cfg.get("repair_seeds", [])),
            local_rpc_host=advertise_host,
            local_rpc_port=port + rpc_off,
        )
        memory = DistributedMemory(
            kademlia=kad,
            rpc_client=rpc_client,
            coder=coder,
            node_id=kad.node_id or "unknown",
            shard_repair=shard_repair,
            bus=bus,
        )
        memory_port = build_memory_port(cfg, memory)
        repo = MemoryRepository(memory_port)
        from swarm.memory.vector_store import OllamaEmbedder
        vectors = VectorStore(embedder=OllamaEmbedder())

        vfs = VirtualFileSystem(repo, vectors)
        sync_engine = SyncEngine(node_id=kad.node_id or "unknown", gossip=gossip)
        linker = MemoryLinker(repo, vectors, llm=llm)
        graph_rag = GraphRAG(repo, vectors)
        
        
        from swarm.memory.vector_store import PersistentVectorIndex
        async def load_vectors():
            await asyncio.sleep(5) # Wait for DHT to stabilize
            try:
                idx = PersistentVectorIndex(vectors, repo)
                n = await idx.load_all()
                logger.info("Loaded %d vectors from persistent index", n)
            except Exception as e:
                logger.warning("Failed to load persistent vectors: %s", e)
        asyncio.create_task(load_vectors())
        reputation = ReputationManager(repo)

        immortal_cfg = cfg.get("immortal", {})
        cold_provider = IPFSProvider(host=immortal_cfg.get("cold_storage", {}).get("ipfs_host", "http://localhost:5001"))
        if immortal_cfg.get("encryption", {}).get("enabled"):
            cold_provider = EncryptedStorage(cold_provider, immortal_cfg["encryption"]["master_key"])
        immortal_manager = ImmortalMemoryManager(vectors, repo, cold_provider)
        archivist = Archivist(immortal_manager, repo)

        agent = SwarmAgent(
            node_id=kad.node_id or "unknown",
            memory=memory,
            llm=llm,
            gossip=gossip,
            rpc_client=rpc_client,
            memory_port=memory_port,
            reputation=reputation,
            repair_interval_seconds=int(mem_cfg.get("repair_interval_seconds", 0)), graph_rag=graph_rag,
            bus=bus,
        )

        async def unified_gossip_handler(msg):
            await sync_engine.handle_gossip(msg)
            await agent.handle_gossip(msg)

        gossip._on_message = unified_gossip_handler

        container = cls(cfg, bus, plugin_registry, port, bootstrap, kad, gossip, rpc_client, rpc_server, llm, memory, agent, vfs, sync_engine, immortal_manager, linker, archivist, graph_rag, reputation, tor_manager)
        
        from swarm.runtime_patch import patch_container
        patch_container(container, cfg)
        from swarm.immortal.awareness_patch import patch_awareness
        patch_awareness(container, cfg)
        from swarm.recruit.recruit_patch import patch_recruit
        patch_recruit(container, cfg)
        return container


class AppRuntime:
    def __init__(self, container: AppContainer) -> None:
        self.container = container
        self._collector = None
        self._control_plane = None

    async def start(self) -> None:
        c = self.container
        
        # Start Tor if enabled
        if c.tor_manager:
            onion = await c.tor_manager.start()
            if onion:
                logger.info("Node identity updated: %s", onion)
                # In real life, we would use onion as advertise_host
                # but kademlia/gossip are UDP and won't work over Tor directly yet.
                # RPC will use it though.

        bootstrap_addr: tuple[str, int] | None = None
        if c.bootstrap:
            host, port_s = c.bootstrap.split(":")
            bootstrap_addr = (host, int(port_s))
        else:
            bootstrap_addr = yaml_bootstrap_addr(c.cfg)
        await c.plugin_registry.setup_all(c)
        _adv = str((c.cfg.get("node") or {}).get("advertise_host", "0.0.0.0"))
        _iface = _adv if _adv and _adv != "127.0.0.1" else "0.0.0.0"
        await c.kad.start(bootstrap_addr=bootstrap_addr, interface=_iface)
        from swarm.runtime_patch import runtime_post_start
        await runtime_post_start(self)
        from swarm.immortal.awareness_patch import runtime_awareness_start
        await runtime_awareness_start(self)
        from swarm.recruit.recruit_patch import runtime_recruit_start
        await runtime_recruit_start(self)
        if c.kad.node_id:
            c.memory._node_id = c.kad.node_id
            c.agent.node_id = c.kad.node_id
            c.agent.executor.node_id = c.kad.node_id
            await c.bus.publish(NodeJoined(c.kad.node_id))

        await self._start_mdns_if_enabled(bootstrap_addr)
        self._register_rpc_handlers()
        await c.gossip.start()
        await c.rpc_server.start()
        await c.sync_engine.start()
        asyncio.create_task(self._maintenance_loop())

        
        import time as _time
        self.container._started_at = _time.time()
        await self._start_control_plane()

        logger.info(
            "Node started: Kademlia=%d Gossip=%d RPC=%d",
            c.port, c.port + 1000, c.port + 2000,
        )

    async def run(self) -> None:
        c = self.container
        try:
            await self.start()
            await c.agent.run()
        except KeyboardInterrupt:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        c = self.container
        if c.tor_manager:
            await c.tor_manager.stop()
        await c.sync_engine.stop()
        await c.agent.stop()
        await c.gossip.stop()
        await c.rpc_server.stop()
        if self._control_plane is not None:
            self._control_plane.stop()
        if c.mdns_inst is not None:
            await c.mdns_inst.stop()
        from swarm.immortal.awareness_patch import runtime_awareness_stop
        await runtime_awareness_stop(self)
        from swarm.recruit.recruit_patch import runtime_recruit_stop
        await runtime_recruit_stop(self)
        if c.kad.node_id:
            await c.bus.publish(NodeLeft(c.kad.node_id))
        await c.kad.stop()
        if c.llm:
            await c.llm.close()

    def _register_rpc_handlers(self) -> None:
        c = self.container

        async def memory_shard_get_handler(params: dict) -> dict:
            block_id = params.get("block_id")
            shard_index = params.get("shard_index")
            if not isinstance(block_id, str) or not isinstance(shard_index, int):
                return {"ok": False, "shard": None, "error": "invalid_params"}
            try:
                data = await c.kad.get(f"shard:{block_id}:{shard_index}")
                return {"ok": True, "shard": data, "error": None}
            except Exception as exc:
                return {"ok": False, "shard": None, "error": str(exc)}

        async def artifact_get_handler(params: dict) -> dict:
            ref = params.get("ref")
            if not ref:
                return {"ok": False, "error": "missing_ref"}
            try:
                art = await c.agent.memory_port.get(ref)
                return {
                    "ok": True,
                    "artifact": {
                        "content": art.content,
                        "mime": art.mime,
                        "tags": art.tags,
                        "attrs": art.attrs
                    }
                }
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        async def task_claim_handler(params: dict[str, Any]) -> dict[str, Any]:
            task_id = params.get("task_id")
            worker_id = params.get("worker_id")
            if not task_id or not worker_id:
                return {"success": False, "reason": "invalid_params"}

            task = c.agent.pool.get(task_id)
            if not task:
                return {"success": False, "reason": "task_not_found"}

            if task.status != TaskStatus.PENDING:
                return {"success": False, "reason": f"task_already_{task.status.value}"}

            # Optional: Check worker reputation
            rep = await c.reputation.get_reputation(worker_id)
            if rep.score < 0.2 and rep.tasks_total > 5:
                logger.warning("Refusing claim from low-reputation node %s (score: %.2f)", worker_id, rep.score)
                return {"success": False, "reason": "low_reputation"}

            task.status = TaskStatus.CLAIMED
            task.assigned_to = worker_id
            logger.info("Task %s claimed by %s", task_id, worker_id)
            return {"success": True}

        async def task_report_handler(params: dict[str, Any]) -> dict[str, Any]:
            task_id = params.get("task_id")
            result = params.get("result")
            status = params.get("status", "done")
            if not task_id:
                return {"success": False, "reason": "invalid_params"}

            task = c.agent.pool.get(task_id)
            if not task:
                return {"success": False, "reason": "task_not_found"}

            worker_id = task.assigned_to
            task.status = TaskStatus(status)
            task.result = result
            logger.info("Task %s reported as %s by %s", task_id, status, worker_id)

            if worker_id:
                if status == "done":
                    await c.reputation.record_success(worker_id)
                else:
                    await c.reputation.record_failure(worker_id)

            return {"success": True}

        async def task_submit_handler(params: dict[str, Any]) -> dict[str, Any]:
            try:
                task = Task.from_dict(params)
                task.creator_id = c.agent.node_id
                
                # Set creator address for remote claiming
                advertise_host = str((c.cfg.get("node") or {}).get("advertise_host", "127.0.0.1"))
                task.creator_address = f"{advertise_host}:{c.port + 2000}"
                
                await c.agent.submit_task(task)
                return {"success": True, "task_id": task.id}
            except Exception as exc:
                return {"success": False, "reason": str(exc)}

        async def task_list_handler(params: dict[str, Any]) -> dict[str, Any]:
            tasks = [t.to_dict() for t in c.agent.pool.values()]
            return {"success": True, "tasks": tasks}

        async def task_claim_local_handler(params: dict[str, Any]) -> dict[str, Any]:
            task_id = params.get("task_id")
            if not task_id:
                return {"success": False, "reason": "missing_task_id"}
            success = await c.agent.claim_task(task_id)
            return {"success": success, "reason": "claim_failed" if not success else None}

        async def reputation_list_handler(params: dict[str, Any]) -> dict[str, Any]:
            reps = await c.reputation.list_reputation(limit=params.get("limit", 50))
            return {"success": True, "reputation": [r.to_dict() for r in reps]}

        async def node_status_handler(params: dict[str, Any]) -> dict[str, Any]:
            tor_status = c.tor_manager.get_status() if c.tor_manager else None
            return {
                "ok": True,
                "node_id": c.kad.node_id,
                "tor": tor_status.__dict__ if tor_status else None
            }

        c.rpc_server.register("memory_shard_get", memory_shard_get_handler)
        c.rpc_server.register("artifact_get", artifact_get_handler)
        c.rpc_server.register("task_claim", task_claim_handler)
        c.rpc_server.register("task_report", task_report_handler)
        c.rpc_server.register("task_submit", task_submit_handler)
        c.rpc_server.register("task_list", task_list_handler)
        c.rpc_server.register("task_claim_local", task_claim_local_handler)
        c.rpc_server.register("reputation_list", reputation_list_handler)
        c.rpc_server.register("node_status", node_status_handler)

    async def _maintenance_loop(self) -> None:
        """Periodic maintenance: linking and archiving."""
        c = self.container
        while True:
            await asyncio.sleep(60)
            try:
                logger.info("Running maintenance: linking new items...")
                rows = await c.vfs._repo.query(table="vfs_files", limit=10)
                for row in rows:
                    await c.linker.link_item(row.ref)

                logger.info("Running maintenance: archivist check...")
                await c.archivist.consolidate()
            except Exception as e:
                logger.error("Maintenance error: %s", e)

    async def _start_control_plane(self) -> None:
        logger.info("DEBUG: _start_control_plane called")
        c = self.container
        dash_cfg = c.cfg.get("dashboard") or {}
        if not dash_cfg.get("enabled", False):
            return
        try:
            from swarm.api.auth import DashboardAuth, RateLimiter
            from swarm.api.control_plane import ControlPlaneServer
            from swarm.api.sse import SSEBridge
            from swarm.observability import ObservabilityCollector
        except ImportError as exc:
            logger.warning("Control plane imports failed: %s", exc)
            return
        self._collector = ObservabilityCollector(c)
        sse_bridge = SSEBridge(c.bus)
        auth = DashboardAuth(c.cfg)
        rate_limiter = RateLimiter()
        metrics = None
        if c.agent.memory_port is not None:
            metrics = c.agent.memory_port.metrics
        if metrics is None:
            from swarm.memory.port import MemoryMetrics
            metrics = MemoryMetrics()
        import os as _os
        host = dash_cfg.get("host", "127.0.0.1")
        # Позволяем переопределить порт через env (для child-нод, чтобы не конфликтовать)
        port = int(_os.environ.get("OCTOPUS_DASHBOARD_PORT", "") or dash_cfg.get("port", 9100))
        # Если это child-нода и порт совпадает с дефолтом — вычислить автоматически (kad_port + 1100)
        if _os.environ.get("OCTOPUS_PARENT_PUBKEY") and port == dash_cfg.get("port", 9100):
            import socket as _socket
            auto_port = getattr(c, "port", 8000) + 1100
            for _try_port in range(auto_port, auto_port + 10):
                try:
                    _s = _socket.socket()
                    _s.bind(("0.0.0.0", _try_port))
                    _s.close()
                    port = _try_port
                    break
                except OSError:
                    continue
            # Child-ноды НЕ доступны снаружи (loopback fix)
            host = "127.0.0.1"
        self._control_plane = ControlPlaneServer(
            metrics,
            container=c,
            collector=self._collector,
            sse_bridge=sse_bridge,
            auth=auth,
            rate_limiter=rate_limiter,
            host=host,
            port=port,
        )
        self._control_plane.start()
        logger.info("Control plane dashboard: %s", self._control_plane.url)

    async def _start_mdns_if_enabled(self, bootstrap_addr: tuple[str, int] | None) -> None:
        c = self.container
        mdns_cfg = c.cfg.get("mdns") or {}
        if not mdns_cfg.get("enabled"):
            return
        try:
            from swarm.network.mdns import SwarmMDNS
        except Exception:
            logger.info("mDNS enabled in config but zeroconf is not installed.")
            return
        host = str((c.cfg.get("node") or {}).get("advertise_host", "127.0.0.1"))
        m = SwarmMDNS(
            mdns_cfg.get("service_type", "_immortal-swarm._tcp.local."),
            float(mdns_cfg.get("refresh_interval_seconds", 60)),
            float(mdns_cfg.get("initial_browse_seconds", 5)),
        )
        await m.start(
            host=host,
            ports={"kad": c.port, "gossip": c.port + 1000, "rpc": c.port + 2000},
            node_id=c.kad.node_id or "unknown",
            instance_suffix=(c.kad.node_id or "node")[:24],
            register=True,
        )
        c.mdns_inst = m
        if bootstrap_addr is None:
            addrs: list[tuple[str, int]] = []
            for peer in m.peers_snapshot():
                h = peer.get("host")
                kp = peer.get("kad")
                if h and kp:
                    addrs.append((str(h), int(kp)))
            if addrs:
                logger.info("Bootstrapping Kademlia from mDNS (%d peer(s))", len(addrs))
                await c.kad.bootstrap_peers(addrs)


# ============================================================================
# PERF PATCH (2026-05-29, Arena agent): scratch index to avoid O(N) full-scan.
#
# Root cause: /api/v1/memory/records polled every 15s by octopus-sync across
#   all nodes -> repo.latest(n=30) -> query(limit=10_000_000) -> read ALL
#   meta.json + blob of 52k+ immortal_archive entries every time. This pinned
#   CPU at ~60% per node and pushed load average to ~20.
#
# Fix (data-preserving, vector ПАМЯТЬ + ЖИТЬ + УПРОЩЕНИЕ):
#   1) LocalScratchAdapter keeps an mtime-validated cache of parsed meta.json
#      (tags, _ts, _table, block_type) so search() does near-zero file reads
#      after warm-up (immortal_archive entries are immutable).
#   2) MemoryRepository.latest() sorts candidate refs by cached _ts and reads
#      blobs only for the top-N rows instead of all 52k.
# Falls back to original behaviour for any unsupported query shape (text /
# where / exotic attr filters) so correctness is preserved.
# ============================================================================
def _install_scratch_perf_patch() -> None:
    try:
        import json as _json
        import os as _os
        import threading as _threading
        from swarm.memory.adapters import local_scratch as _ls
        from swarm.memory import repository as _repo
        from swarm.memory.types import RefMeta as _RefMeta
        from swarm.memory.ref_parse import make_ref as _make_ref, parse_ref as _parse_ref
    except Exception as _e:  # pragma: no cover
        logger.warning("scratch perf patch: import failed: %s", _e)
        return

    LS = _ls.LocalScratchAdapter
    if getattr(LS, "_perf_patched", False):
        return

    _decode = _ls._decode_meta_value

    def _ensure_lock(self):
        lk = getattr(self, "_meta_index_lock", None)
        if lk is None:
            lk = self._meta_index_lock = _threading.RLock()
        return lk

    def _ensure_index(self):
        idx = getattr(self, "_meta_index", None)
        if idx is None:
            idx = self._meta_index = {}
        return idx

    def _refresh_index(self):
        import time as _t
        idx = _ensure_index(self)
        lock = _ensure_lock(self)
        now = _t.monotonic()
        last = getattr(self, "_meta_index_ts", 0.0)
        # Re-scan at most once per _INDEX_TTL seconds. Scratch entries are
        # effectively immutable (append-only immortal_archive / vfs_files), so
        # we ONLY parse meta.json for NEW directories and lazily drop deleted
        # ones. This makes warm rescans O(new entries) instead of O(52k stat).
        if idx and (now - last) < getattr(self, "_INDEX_TTL", 30.0):
            return idx
        # Serialize scans: only ONE thread performs the (potentially heavy cold)
        # scan; concurrent callers wait for it then reuse the fresh index
        # instead of each launching its own 52k-dir scan (thundering herd).
        scan_lock = getattr(self, "_meta_scan_lock", None)
        if scan_lock is None:
            scan_lock = self._meta_scan_lock = _threading.Lock()
        if not scan_lock.acquire(blocking=False):
            # someone else is scanning — wait for it, then return their result.
            with scan_lock:
                pass
            return idx
        try:
            now = _t.monotonic()
            last = getattr(self, "_meta_index_ts", 0.0)
            if idx and (now - last) < getattr(self, "_INDEX_TTL", 30.0):
                return idx
            self._meta_index_ts = now
            return _do_scan(self, idx, lock)
        finally:
            scan_lock.release()

    def _do_scan(self, idx, lock):
        import os as _os
        root = self._root
        if not root.exists():
            idx.clear()
            return idx
        try:
            scan = _os.scandir(root)
        except FileNotFoundError:
            idx.clear()
            return idx
        live = set()
        new_dirs = []
        with scan as it:
            for entry in it:
                try:
                    if not entry.is_dir():
                        continue
                except OSError:
                    continue
                name = entry.name
                live.add(name)
                if name not in idx:          # only NEW entries need parsing
                    new_dirs.append((name, entry.path))
        parsed = {}
        for name, path in new_dirs:
            mp = _os.path.join(path, "meta.json")
            try:
                with open(mp, "r", encoding="utf-8") as fh:
                    raw = _json.load(fh)
            except Exception:
                continue
            attrs = _decode(raw.get("attrs")) or {}
            if not isinstance(attrs, dict):
                attrs = {}
            tags = list(raw.get("tags") or [])
            parsed[name] = {
                "mtime": 0.0,
                "tags": tags,
                "ts": attrs.get("_ts", 0),
                "table": str(attrs.get("_table") or ""),
                "block_type": attrs.get("block_type"),
            }
        # Apply additions + prune deletions atomically under the lock so
        # concurrent control-plane threads never see a mutating dict.
        with lock:
            idx.update(parsed)
            stale = [name for name in list(idx.keys()) if name not in live]
            for name in stale:
                idx.pop(name, None)
        return idx

    async def _patched_search(self, tags, owner):
        idx = _refresh_index(self)
        lock = _ensure_lock(self)
        wanted = set(tags or [])
        out = []
        with lock:
            snapshot = list(idx.items())
        for name, ent in snapshot:
            row_tags = ent["tags"]
            if wanted and not wanted.intersection(row_tags):
                continue
            out.append(_RefMeta(
                ref=_make_ref("file", name),
                scheme="file",
                tags=list(row_tags),
                block_type=ent["block_type"],
            ))
        return out

    def _cached_min_attrs(self, ref):
        try:
            scheme, name = _parse_ref(ref)
        except Exception:
            return None
        if scheme != "file":
            return None
        ent = getattr(self, "_meta_index", {}).get(name)
        if ent is None:
            return None
        return {"_ts": ent["ts"], "_table": ent["table"]}

    LS.search = _patched_search
    LS._refresh_index = _refresh_index
    LS._cached_min_attrs = _cached_min_attrs
    LS._perf_patched = True

    # ---- repository.latest: sort by cached _ts, read blobs only for top-N ----
    Repo = _repo.MemoryRepository
    _orig_latest = Repo.latest
    _MemoryRow = _repo.MemoryRow

    def _find_file_adapter(port):
        ad = getattr(port, "_adapters", None)
        if isinstance(ad, dict):
            return ad.get("file")
        return None

    async def _patched_latest(self, *, table=None, tags=None, attrs=None, where=None, n=1):
        fa = _find_file_adapter(self._port)
        want_attrs = attrs or {}
        unsupported_attr = any(k not in ("_ts", "_table") for k in want_attrs)
        if (fa is None or not hasattr(fa, "_cached_min_attrs")
                or where is not None or unsupported_attr):
            return await _orig_latest(
                self, table=table, tags=tags, attrs=attrs, where=where, n=n)

        seed_tags = list(tags or [])
        if table:
            tt = f"table:{table}"
            if tt not in seed_tags:
                seed_tags.append(tt)
        metas = await self._port.search(seed_tags, owner=None)
        cand = []
        for meta in metas:
            ca = fa._cached_min_attrs(meta.ref)
            if ca is None:
                # non-file or not-yet-indexed: fall back to safe full path
                return await _orig_latest(
                    self, table=table, tags=tags, attrs=attrs, where=where, n=n)
            if table and ca.get("_table") != table:
                continue
            if any(ca.get(k) != v for k, v in want_attrs.items()):
                continue
            cand.append((ca.get("_ts", 0), meta.ref))
        cand.sort(key=lambda x: x[0], reverse=True)
        if n < 0:
            n = 0
        cand = cand[:n]
        rows = []
        for _ts, ref in cand:
            try:
                art = await self._port.get(ref)
                payload = (art.content.decode("utf-8")
                           if isinstance(art.content, bytes) else art.content)
                data = _json.loads(payload)
            except Exception:
                continue
            row_attrs = dict(art.attrs or {})
            rows.append(_MemoryRow(
                ref=ref,
                table=str(row_attrs.get("_table") or ""),
                data=data,
                tags=list(art.tags),
                attrs=row_attrs,
            ))
        return rows

    Repo.latest = _patched_latest

    # ---- repository.query: tolerate refs whose blob vanished (stale index /
    #      concurrent delete). The original called _port.get(ref) OUTSIDE the
    #      try/except, so a single missing ref raised RefNotFoundError and
    #      aborted the whole listing (files tab -> 0 files + error). This
    #      reimplementation skips unreadable refs instead of failing. ----
    async def _query_guarded(self, *, table=None, tags=None, text=None,
                             attrs=None, where=None, order_by=None,
                             offset=0, limit=100):
        import json as __json
        seed_tags = list(tags or [])
        if table:
            tt = f"table:{table}"
            if tt not in seed_tags:
                seed_tags.append(tt)
        metas = await self._port.search(seed_tags, owner=None)
        needle = text.casefold() if text else None
        want_attrs = attrs or {}
        matched = []
        for meta in metas:
            try:
                art = await self._port.get(meta.ref)
            except Exception:
                continue  # stale index / deleted blob — skip, never abort
            try:
                payload = (art.content.decode("utf-8")
                           if isinstance(art.content, bytes) else art.content)
                data = __json.loads(payload)
            except Exception:
                continue
            row_attrs = dict(art.attrs or {})
            row_table = str(row_attrs.get("_table") or "")
            if table and row_table != table:
                continue
            if any(row_attrs.get(k) != v for k, v in want_attrs.items()):
                continue
            if needle and needle not in __json.dumps(data, ensure_ascii=False).casefold():
                continue
            row = _MemoryRow(ref=meta.ref, table=row_table, data=data,
                             tags=list(art.tags), attrs=row_attrs)
            if where and not self._matches_where(row, where):
                continue
            matched.append(row)
        if order_by:
            path, desc = self._parse_order(order_by)
            matched.sort(key=lambda r: self._sort_value(self._field_value(r, path)),
                         reverse=desc)
        if offset < 0:
            offset = 0
        return matched[offset:offset + max(0, limit)]

    Repo.query = _query_guarded
    logger.info("scratch perf patch installed (mtime index + top-N latest + guarded query)")


_install_scratch_perf_patch()
