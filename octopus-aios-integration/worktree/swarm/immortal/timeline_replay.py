from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .timeline import TemporalLog


@dataclass
class ReplayFrame:
    index: int
    kind: str
    payload: dict[str, Any]


class TimelineReplay:
    """Reconstructs swarm evolution from temporal events."""

    def __init__(self, log: TemporalLog) -> None:
        self.log = log

    def frames(self) -> list[ReplayFrame]:
        result: list[ReplayFrame] = []
        for index, event in enumerate(self.log.replay()):
            result.append(
                ReplayFrame(
                    index=index,
                    kind=event.kind,
                    payload=event.payload,
                )
            )
        return result

    def summarize(self) -> dict[str, Any]:
        frames = self.frames()
        return {
            "events": len(frames),
            "kinds": sorted({frame.kind for frame in frames}),
        }
