"""Immortal node runtime primitives for Octopus/Gemaxi.

This package contains the first production-shaped skeleton for node immortality:
state-first execution, append-only DAG commits, rehydration, ghost execution,
and causal distributed memory primitives.
"""

from .state_dag import StateDag, StatePatch, StateCommit
from .ghost_executor import GhostExecutor, GhostResult
from .rehydration import Rehydrator, RehydrationSnapshot
from .crdt_memory import LwwMap, LwwValue
from .verifier import MajorityVerifier
from .vector_clock import VectorClock

__all__ = [
    "StateDag",
    "StatePatch",
    "StateCommit",
    "GhostExecutor",
    "GhostResult",
    "Rehydrator",
    "RehydrationSnapshot",
    "LwwMap",
    "LwwValue",
    "MajorityVerifier",
    "VectorClock",
]
