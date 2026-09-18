from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from time import time
from typing import Any


@dataclass
class IdentityClaim:
    subject: str
    predicate: str
    value: Any
    ts: float = field(default_factory=time)

    @property
    def claim_id(self) -> str:
        raw = f"{self.subject}:{self.predicate}:{repr(self.value)}:{self.ts}".encode()
        return sha256(raw).hexdigest()


@dataclass
class SwarmIdentity:
    swarm_id: str
    claims: dict[str, IdentityClaim] = field(default_factory=dict)

    def assert_claim(self, predicate: str, value: Any) -> str:
        claim = IdentityClaim(
            subject=self.swarm_id,
            predicate=predicate,
            value=value,
        )
        self.claims[claim.claim_id] = claim
        return claim.claim_id

    def fingerprint(self) -> str:
        parts = sorted(
            f"{claim.subject}:{claim.predicate}:{repr(claim.value)}"
            for claim in self.claims.values()
        )
        return sha256("|".join(parts).encode()).hexdigest()

    def export(self) -> dict[str, Any]:
        return {
            "swarm_id": self.swarm_id,
            "fingerprint": self.fingerprint(),
            "claims": {
                claim_id: {
                    "subject": claim.subject,
                    "predicate": claim.predicate,
                    "value": claim.value,
                    "ts": claim.ts,
                }
                for claim_id, claim in self.claims.items()
            },
        }
