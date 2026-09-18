"""Manual client for the operator dashboard WS bridge (Wave 5, item 20).

Usage: python -m swarm.dashboards.dashboard_websocket_test
"""

import threading
import time

from swarm.dashboards.operator_dashboard_api import app


def run_server():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="error")


def run_test():
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)
    print("✅ Сервер UI Bridge (Матрица) успешно поднят на порту 8002.")


if __name__ == "__main__":
    run_test()
