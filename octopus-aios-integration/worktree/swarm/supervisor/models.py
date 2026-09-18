"""Small, dependency-free models for agent supervision."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SupervisorTask:
    task_id: str
    title: str
    description: str
    risk_level: str = "normal"
    budget_agents: int = 4
    budget_retries: int = 2


@dataclass(frozen=True)
class AgentCandidate:
    role: str
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SupervisorDecision:
    selected: tuple[AgentCandidate, ...]
    parallel: bool = True
    reason: str = ""
    estimated_agents: int = 0
