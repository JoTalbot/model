"""
swarm/immortal/node_self.py
────────────────────────────
NodeSelf — самосознание ноды.

Нода знает о себе:
  • node_id, role, skills
  • текущая нагрузка (задачи, память, gossip)
  • состояние здоровья (health score 0.0–1.0)
  • время жизни (uptime)
  • метаданные (version, spawned_by, platform)

NodeSelf периодически:
  1. Обновляет snapshot своего состояния
  2. Рассылает его через Gossip (тип NODE_AWARENESS)
  3. Принимает awareness от пиров → строит карту роя

Интеграция с существующим AwarenessPropagation:
  NodeSelf.observe() → AwarenessPropagation.observe()
  NodeSelf.export()  → AwarerenessState → gossip payload
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Типы
# ══════════════════════════════════════════════════════════════════════════════

class NodeRole(str, Enum):
    WORKER     = "worker"      # выполняет задачи
    RECRUITER  = "recruiter"   # набирает новые ноды
    COORDINATOR = "coordinator" # координирует рой
    OBSERVER   = "observer"    # только слушает
    HYBRID     = "hybrid"      # всё сразу


class HealthStatus(str, Enum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    OVERLOADED = "overloaded"
    DYING     = "dying"


@dataclass
class SkillDescriptor:
    """Описание навыка, которым владеет нода."""
    name:        str
    version:     str  = "1.0"
    capacity:    int  = 1       # сколько задач этого типа может параллельно
    description: str  = ""


@dataclass
class LoadSnapshot:
    """Текущая нагрузка ноды."""
    tasks_pending:  int   = 0
    tasks_running:  int   = 0
    tasks_done:     int   = 0
    gossip_rx:      int   = 0
    gossip_tx:      int   = 0
    peers_count:    int   = 0
    memory_items:   int   = 0
    cpu_percent:    float = 0.0   # опционально
    ram_mb:         float = 0.0   # опционально


@dataclass
class NodeSnapshot:
    """Полный снимок состояния ноды для gossip."""
    node_id:      str
    role:         str
    skills:       list[dict]
    health:       str
    health_score: float          # 0.0 (мёртв) – 1.0 (отлично)
    load:         dict
    uptime_sec:   float
    version:      str
    platform_info: str
    spawned_by:   str            # node_id родителя (если спавн)
    ts:           float = field(default_factory=time.time)
    extra:        dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        d = asdict(self)
        return d


# ══════════════════════════════════════════════════════════════════════════════
# NodeSelf
# ══════════════════════════════════════════════════════════════════════════════

class NodeSelf:
    """
    Самосознание ноды — знает себя, рассказывает о себе рою.

    Использование:
        self_node = NodeSelf(node_id="abc", role=NodeRole.HYBRID)
        self_node.register_skill(SkillDescriptor("web_parser"))
        self_node.register_skill(SkillDescriptor("note_search"))
        self_node.start(gossip=gossip_protocol)
        # → каждые broadcast_interval секунд рассылает NODE_AWARENESS
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        *,
        node_id:    str,
        role:       NodeRole = NodeRole.HYBRID,
        spawned_by: str = "",
        broadcast_interval: float = 30.0,
    ) -> None:
        self.node_id   = node_id
        self.role      = role
        self.spawned_by = spawned_by
        self.broadcast_interval = broadcast_interval

        self._skills:      list[SkillDescriptor] = []
        self._start_time:  float = time.time()
        self._task:        asyncio.Task | None = None
        self._gossip       = None

        # Карта роя: node_id → NodeSnapshot
        self._swarm_map: dict[str, NodeSnapshot] = {}

        # Интеграция с существующим AwarenessPropagation
        self._awareness = None

        self._platform = f"{platform.system()} {platform.machine()} py{sys.version[:6]}"

    # ── Скиллы ───────────────────────────────────────────────────────────────

    def register_skill(self, skill: SkillDescriptor) -> None:
        if not any(s.name == skill.name for s in self._skills):
            self._skills.append(skill)
            logger.debug("NodeSelf [%s]: зарегистрирован навык %s", self.node_id, skill.name)

    def register_skill_from_name(self, name: str, **kwargs) -> None:
        self.register_skill(SkillDescriptor(name=name, **kwargs))

    def unregister_skill(self, name: str) -> None:
        self._skills = [s for s in self._skills if s.name != name]

    def has_skill(self, name: str) -> bool:
        return any(s.name == name for s in self._skills)

    # ── Старт / стоп ─────────────────────────────────────────────────────────

    def start(self, gossip) -> None:
        self._gossip = gossip
        self._task   = asyncio.create_task(self._broadcast_loop())
        logger.info(
            "NodeSelf [%s] started: role=%s, skills=%s",
            self.node_id, self.role.value,
            [s.name for s in self._skills],
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # ── Интеграция с AwarenessPropagation ────────────────────────────────────

    def attach_awareness(self, awareness) -> None:
        """Подключить существующий AwarenessPropagation из immortal/awareness.py."""
        self._awareness = awareness

    # ── Наблюдение ───────────────────────────────────────────────────────────

    def observe_load(self, load: LoadSnapshot) -> None:
        """Зафиксировать текущую нагрузку (вызывается из runtime)."""
        self._current_load = load

        # Пробрасываем в AwarenessPropagation если подключён
        if self._awareness:
            from swarm.immortal.coordination import CoordinationSignalKind
            if load.tasks_pending > 10:
                self._awareness.observe(
                    CoordinationSignalKind.EXECUTION_BACKLOG,
                    {"replicas": 1, "node_id": self.node_id},
                )
            if load.memory_items > 1000:
                self._awareness.observe(
                    CoordinationSignalKind.MEMORY_PRESSURE,
                    {"key": "global", "node_id": self.node_id},
                )

    # ── Вычисление health score ───────────────────────────────────────────────

    def _compute_health(self, load: LoadSnapshot) -> tuple[float, HealthStatus]:
        """
        Простая эвристика health score.
        Возвращает (score: float, status: HealthStatus).
        """
        score = 1.0
        # Очередь задач → давление
        if load.tasks_pending > 20:
            score -= 0.4
        elif load.tasks_pending > 10:
            score -= 0.2
        # CPU
        if load.cpu_percent > 90:
            score -= 0.3
        elif load.cpu_percent > 70:
            score -= 0.1
        # RAM
        if load.ram_mb > 1024:
            score -= 0.2

        score = max(0.0, min(1.0, score))

        if score >= 0.8:
            status = HealthStatus.HEALTHY
        elif score >= 0.5:
            status = HealthStatus.DEGRADED
        elif score >= 0.2:
            status = HealthStatus.OVERLOADED
        else:
            status = HealthStatus.DYING

        return score, status

    # ── Снимок состояния ──────────────────────────────────────────────────────

    def snapshot(self, load: LoadSnapshot | None = None) -> NodeSnapshot:
        """Создать текущий снимок состояния ноды."""
        if load is None:
            load = getattr(self, "_current_load", LoadSnapshot())

        score, status = self._compute_health(load)

        return NodeSnapshot(
            node_id=self.node_id,
            role=self.role.value,
            skills=[asdict(s) for s in self._skills],
            health=status.value,
            health_score=round(score, 3),
            load=asdict(load),
            uptime_sec=round(time.time() - self._start_time, 1),
            version=self.VERSION,
            platform_info=self._platform,
            spawned_by=self.spawned_by,
        )

    # ── Gossip-рассылка ───────────────────────────────────────────────────────

    async def broadcast(self, load: LoadSnapshot | None = None) -> None:
        """Немедленно разослать NODE_AWARENESS через gossip."""
        if not self._gossip:
            return
        from swarm.network.gossip import GossipMessage
        snap = self.snapshot(load)
        msg  = GossipMessage(
            msg_type="NODE_AWARENESS",
            payload=snap.to_payload(),
        )
        await self._gossip.inject(msg)
        logger.debug(
            "NodeSelf [%s]: broadcast NODE_AWARENESS (health=%s score=%.2f)",
            self.node_id, snap.health, snap.health_score,
        )

    async def _broadcast_loop(self) -> None:
        while True:
            try:
                await self.broadcast()
            except Exception as exc:
                logger.warning("NodeSelf broadcast error: %s", exc)
            await asyncio.sleep(self.broadcast_interval)

    # ── Приём awareness от пиров ──────────────────────────────────────────────

    async def handle_gossip(self, msg) -> None:
        """Обработчик для unified_gossip_handler."""
        if msg.msg_type != "NODE_AWARENESS":
            return
        payload = msg.payload
        nid = payload.get("node_id", "")
        if not nid or nid == self.node_id:
            return
        try:
            snap = NodeSnapshot(**payload)
            self._swarm_map[nid] = snap
            logger.debug(
                "NodeSelf: получен awareness от %s (role=%s health=%s score=%.2f)",
                nid[:12], snap.role, snap.health, snap.health_score,
            )
        except Exception as exc:
            logger.debug("NodeSelf: ошибка парсинга awareness: %s", exc)

    # ── Карта роя ─────────────────────────────────────────────────────────────

    def swarm_map(self) -> dict[str, NodeSnapshot]:
        """Известные ноды роя (исключая себя)."""
        return dict(self._swarm_map)

    def find_nodes_with_skill(self, skill_name: str) -> list[NodeSnapshot]:
        """Найти ноды с нужным навыком."""
        return [
            snap for snap in self._swarm_map.values()
            if any(s.get("name") == skill_name for s in snap.skills)
        ]

    def find_healthiest(self, n: int = 3) -> list[NodeSnapshot]:
        """Найти N самых здоровых нод."""
        return sorted(
            self._swarm_map.values(),
            key=lambda s: s.health_score,
            reverse=True,
        )[:n]

    def find_idle_workers(self) -> list[NodeSnapshot]:
        """Найти ноды с малой нагрузкой."""
        return [
            s for s in self._swarm_map.values()
            if s.health == HealthStatus.HEALTHY.value
            and s.load.get("tasks_pending", 99) < 3
        ]

    def prune_stale(self, ttl: float = 120.0) -> int:
        """Удалить ноды, от которых давно не было awareness."""
        now   = time.time()
        stale = [nid for nid, s in self._swarm_map.items() if now - s.ts > ttl]
        for nid in stale:
            del self._swarm_map[nid]
        if stale:
            logger.info("NodeSelf: удалено %d устаревших нод из карты", len(stale))
        return len(stale)

    # ── Статистика ────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "node_id":       self.node_id,
            "role":          self.role.value,
            "skills":        [s.name for s in self._skills],
            "health":        snap.health,
            "health_score":  snap.health_score,
            "uptime_sec":    snap.uptime_sec,
            "swarm_map_size": len(self._swarm_map),
            "known_roles":   list({s.role for s in self._swarm_map.values()}),
            "known_skills":  list({
                sk["name"]
                for s in self._swarm_map.values()
                for sk in s.skills
            }),
        }
