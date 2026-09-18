# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: upstream refs to aios_core.container/web_gui are dangling
"""Run AIOS Dashboard"""

import argparse
import os

import uvicorn


def auto_seed_db():
    try:
        from swarm.dashboards.seed_dashboard_data import seed
        seed()
    except Exception as e:
        print(f"⚠️ Auto-seed info: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("AIOS_DASH_HOST", "0.0.0.0"))
    parser.add_argument("--port", default=int(os.environ.get("AIOS_DASH_PORT", "8080")), type=int)
    args = parser.parse_args()

    auto_seed_db()

    from aios_core.container import container
    from aios_core.dashboard import create_dashboard

    container.db()
    orch = container.orchestrator()

    app = create_dashboard(orch)
    print(f"🌐 Starting AIOS Dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


_app = None


def _get_app():
    global _app
    if _app is None:
        auto_seed_db()
        from aios_core.container import container
        from aios_core.dashboard import create_dashboard

        container.db()
        orch = container.orchestrator()
        _app = create_dashboard(orch)
    return _app


app = _get_app()
if __name__ == "__main__":
    main()
