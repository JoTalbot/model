from __future__ import annotations


class Plugin:
    name: str = "base"

    async def setup(self, container) -> None:
        """Register hooks/adapters/commands against the runtime container."""
