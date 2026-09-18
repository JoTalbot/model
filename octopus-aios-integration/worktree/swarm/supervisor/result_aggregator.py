"""Aggregate specialist execution results into a deterministic supervisor decision."""

from __future__ import annotations

from dataclasses import dataclass

from .conflict_resolver import ConflictResolver, SpecialistOpinion
from .execution_engine import ExecutionResult


@dataclass(frozen=True)
class AggregatedResult:
    decision: str
    resolved: bool
    reason: str
    successful_roles: tuple[str, ...] = ()
    failed_roles: tuple[str, ...] = ()


class ResultAggregator:
    """Convert execution outcomes into APPROVE/RETRY/REPLAN/BLOCK."""

    def __init__(self, resolver: ConflictResolver | None = None) -> None:
        self._resolver = resolver or ConflictResolver()

    def aggregate(self, results: tuple[ExecutionResult, ...]) -> AggregatedResult:
        if not results:
            return AggregatedResult("BLOCK", False, "no specialist execution results")

        failed = tuple(result.role for result in results if not result.success)
        successful = tuple(result.role for result in results if result.success)
        if failed:
            return AggregatedResult(
                "RETRY",
                False,
                f"specialist execution failed: {', '.join(failed)}",
                successful,
                failed,
            )

        opinions = tuple(
            SpecialistOpinion(
                role=result.role,
                decision="APPROVED",
                confidence=1.0,
                evidence=("execution completed successfully",),
            )
            for result in results
        )
        conflict = self._resolver.resolve(opinions)
        if conflict.resolved and conflict.decision == "APPROVED":
            return AggregatedResult("APPROVE", True, conflict.reason, successful, ())
        return AggregatedResult("BLOCK", False, conflict.reason, successful, ())
