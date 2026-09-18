from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class CoordinationSignalKind(str, Enum):
    MEMORY_PRESSURE = "memory_pressure"
    PEER_DEGRADED = "peer_degraded"
    EXECUTION_BACKLOG = "execution_backlog"
    REPLICATION_GAP = "replication_gap"
    TOPOLOGY_PARTITION = "topology_partition"


class CoordinationActionKind(str, Enum):
    REPLICATE_MEMORY = "replicate_memory"
    AVOID_PEER = "avoid_peer"
    SPAWN_EXECUTION = "spawn_execution"
    REQUEST_SNAPSHOT = "request_snapshot"
    REPAIR_TOPOLOGY = "repair_topology"


@dataclass
class CoordinationSignal:
    kind: CoordinationSignalKind
    payload: dict[str, Any]
    ts: float = field(default_factory=time)


@dataclass
class CoordinationAction:
    kind: CoordinationActionKind
    payload: dict[str, Any]
    reason: str


class EmergentCoordinator:
    """Converts local swarm signals into self-balancing actions.

    This is the first step toward emergent coordination: the system observes
    pressure, degradation and topology problems, then proposes actions without
    requiring a central controller.
    """

    def decide(self, signals: list[CoordinationSignal]) -> list[CoordinationAction]:
        actions: list[CoordinationAction] = []

        for signal in signals:
            if signal.kind == CoordinationSignalKind.MEMORY_PRESSURE:
                actions.append(
                    CoordinationAction(
                        kind=CoordinationActionKind.REPLICATE_MEMORY,
                        payload={"key": signal.payload.get("key")},
                        reason="memory pressure detected",
                    )
                )

            elif signal.kind == CoordinationSignalKind.PEER_DEGRADED:
                actions.append(
                    CoordinationAction(
                        kind=CoordinationActionKind.AVOID_PEER,
                        payload={"peer_id": signal.payload.get("peer_id")},
                        reason="peer health degraded",
                    )
                )

            elif signal.kind == CoordinationSignalKind.EXECUTION_BACKLOG:
                actions.append(
                    CoordinationAction(
                        kind=CoordinationActionKind.SPAWN_EXECUTION,
                        payload={"replicas": signal.payload.get("replicas", 1)},
                        reason="execution backlog detected",
                    )
                )

            elif signal.kind == CoordinationSignalKind.REPLICATION_GAP:
                actions.append(
                    CoordinationAction(
                        kind=CoordinationActionKind.REQUEST_SNAPSHOT,
                        payload={"key": signal.payload.get("key")},
                        reason="replication gap detected",
                    )
                )

            elif signal.kind == CoordinationSignalKind.TOPOLOGY_PARTITION:
                actions.append(
                    CoordinationAction(
                        kind=CoordinationActionKind.REPAIR_TOPOLOGY,
                        payload={"partition": signal.payload},
                        reason="topology partition detected",
                    )
                )

        return actions


# ══════════════════════════════════════════════════════════════════════════════
# SwarmGoal — глобальная цель / миссия роя
# ══════════════════════════════════════════════════════════════════════════════

class SwarmGoalKind(str, Enum):
    EXPAND        = "expand"        # Размножаться — добавлять новые ноды
    LEARN         = "learn"         # Учиться — накапливать знания в памяти
    OPTIMIZE      = "optimize"      # Оптимизировать — улучшать latency/throughput
    SURVIVE       = "survive"       # Выживать — восстанавливаться при падениях
    COLLABORATE   = "collaborate"   # Сотрудничать — делиться задачами между нодами


@dataclass
class SwarmGoal:
    kind: SwarmGoalKind
    description: str
    priority: int = 5        # 1–10
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time)


# Глобальная цель — Проект Октопус: ПРОЦЕСС
OCTOPUS_MISSION: list[SwarmGoal] = [
    SwarmGoal(SwarmGoalKind.SURVIVE,      "Поддерживать непрерывность работы всех нод",         priority=10),
    SwarmGoal(SwarmGoalKind.EXPAND,       "Увеличить рой до 5+ нод",                            priority=8),
    SwarmGoal(SwarmGoalKind.LEARN,        "Накапливать знания через TG-бот и задачи",           priority=7),
    SwarmGoal(SwarmGoalKind.COLLABORATE,  "Распределять задачи между нодами",                   priority=6),
    SwarmGoal(SwarmGoalKind.OPTIMIZE,     "Снизить latency gossip и RPC до минимума",           priority=5),
]


class GoalAwareCoordinator(EmergentCoordinator):
    """
    Расширение EmergentCoordinator — учитывает глобальные цели роя.
    При принятии решений сначала проверяет SURVIVE, затем EXPAND и т.д.
    """

    def __init__(self, goals: list[SwarmGoal] | None = None) -> None:
        self._goals = sorted(goals or OCTOPUS_MISSION, key=lambda g: -g.priority)

    def decide_with_goals(
        self,
        signals: list[CoordinationSignal],
        current_peers: int = 0,
    ) -> list[CoordinationAction]:
        actions = self.decide(signals)

        for goal in self._goals:
            if goal.kind == SwarmGoalKind.EXPAND and current_peers < 4:
                actions.append(CoordinationAction(
                    kind=CoordinationActionKind.SPAWN_EXECUTION,
                    payload={"reason": "goal:expand", "target_peers": 5},
                    reason=f"SwarmGoal EXPAND: {goal.description}",
                ))
            elif goal.kind == SwarmGoalKind.SURVIVE:
                actions.append(CoordinationAction(
                    kind=CoordinationActionKind.REQUEST_SNAPSHOT,
                    payload={"reason": "goal:survive", "interval": 3600},
                    reason=f"SwarmGoal SURVIVE: {goal.description}",
                ))

        return actions

    def active_goals(self) -> list[dict]:
        return [
            {"kind": g.kind, "description": g.description,
             "priority": g.priority, "ts": g.ts}
            for g in self._goals
        ]
