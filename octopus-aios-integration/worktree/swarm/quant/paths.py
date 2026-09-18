"""Shared data-dir resolution for swarm.quant (Wave 4, item 1).

AIOS hard-coded an absolute data dir plus a Docker sniff-block in every engine
class. The port uses an explicit argument or ``OCTOPUS_DATA_DIR``
(``/var/lib/octopus``). No Docker sniffing: octopus does not run in Docker.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))


def resolve_data_dir(data_dir: str | Path | None = None) -> Path:
    """Explicit path wins, otherwise OCTOPUS_DATA_DIR (read live for tests)."""
    if data_dir is not None:
        return Path(data_dir)
    return Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))
