from __future__ import annotations

from collections import Counter
from typing import Any

from .ghost_executor import GhostResult


class MajorityVerifier:
    """Simple consensus verifier.

    Future versions can use weighted trust, cryptographic signatures,
    semantic equivalence or deterministic replay.
    """

    def verify(self, results: list[GhostResult]) -> dict[str, Any]:
        successful = [r for r in results if r.success]

        if not successful:
            return {
                "accepted": False,
                "reason": "no successful executions",
            }

        counter = Counter(repr(r.result) for r in successful)
        winner, votes = counter.most_common(1)[0]

        return {
            "accepted": True,
            "winner": winner,
            "votes": votes,
            "participants": len(successful),
        }
