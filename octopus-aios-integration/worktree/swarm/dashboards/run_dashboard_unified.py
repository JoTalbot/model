# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: upstream refs to aios_core.container/web_gui are dangling
#!/usr/bin/env python3
"""Run AIOS unified dashboard: FastAPI backend + NiceGUI frontend."""

from __future__ import annotations

import os
import threading
import time

import uvicorn


def _run_fastapi(port: int) -> None:
    from aios_core.container import container
    from aios_core.dashboard import create_dashboard

    container.db()
    orch = container.orchestrator()
    app = create_dashboard(orch)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def _run_nicegui() -> None:
    from aios_core.web_gui.main import run

    run()


def main() -> int:
    api_port = int(os.environ.get("AIOS_DASH_PORT", "8580"))

    api_thread = threading.Thread(
        target=_run_fastapi,
        args=(api_port,),
        daemon=True,
    )
    api_thread.start()

    time.sleep(2)

    _run_nicegui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
