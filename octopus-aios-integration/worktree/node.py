from __future__ import annotations

import sys

from swarm import cli as _cli_module
from swarm import entrypoint as _entrypoint_module


def _ensure_legacy_commands() -> None:
    if hasattr(_cli_module, "memory") and "memory" not in _cli_module.cli.commands:
        _cli_module.cli.add_command(_cli_module.memory, "memory")


_ensure_legacy_commands()

# Keep `from node import cli` and test monkeypatches compatible even when
# Python returns this wrapper module rather than the substituted swarm.cli module.
cli = _cli_module.cli
_build_cloud_memory_port = _cli_module._build_cloud_memory_port
_build_local_memory_port = _cli_module._build_local_memory_port
_build_local_memory_repository = _cli_module._build_local_memory_repository

if __name__ == "__main__":
    raise SystemExit(_entrypoint_module.main())
else:
    sys.modules[__name__] = _cli_module
