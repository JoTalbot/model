"""Deterministic conflict handling for specialist outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistOpinion:
    role: str
    decision: str
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConflictDecision:
    decision: str
    resolved: bool
    reason: str
    supporting_roles: tuple[str, ...] = ()


class ConflictResolver:
    """Resolve only when evidence supports a deterministic winner."""

    def resolve(self, opinions: tuple[SpecialistOpinion, ...]) -> ConflictDecision:
        if not opinions:
            return ConflictDecision("UNRESOLVED", False, "no specialist opinions")

        grouped: dict[str, list[SpecialistOpinion]] = {}
        for opinion in opinions:
            grouped.setdefault(opinion.decision, []).append(opinion)

        ranked = sorted(
            grouped.items(),
            key=lambda item: (
                sum(max(0.0, opinion.confidence) for opinion in item[1]),
                len(item[1]),
                item[0],
            ),
            reverse=True,
        )
        winner, supporters = ranked[0]
        total = sum(max(0.0, opinion.confidence) for opinion in supporters)
        runner_up = ranked[1][1] if len(ranked) > 1 else []
        runner_score = sum(max(0.0, opinion.confidence) for opinion in runner_up)

        if len(ranked) > 1 and total <= runner_score:
            return ConflictDecision("UNRESOLVED", False, "conflicting opinions lack a clear evidence-weighted winner")

        roles = tuple(sorted(opinion.role for opinion in supporters))
        return ConflictDecision(winner, True, f"evidence-weighted winner: {winner}", roles)
