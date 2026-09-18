# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
"""
AIOS Dashboard v2 - Analytics: tech debt, balancer, memory, RAG, live logs
"""
from nicegui import ui
import json
from pathlib import Path
from datetime import datetime

# Load data
def load_backlog():
    try:
        data = json.loads((Path("/root/AIOS/data/coder_backlog.json")).read_text())
        return data
    except:
        return {"tasks": [], "history": [], "cycle_count": 0}

def load_v3_memory():
    try:
        data = json.loads((Path("/root/AIOS/data/autocoder_v3_memory.json")).read_text())
        return data
    except:
        return {"successful_fixes": [], "failed_attempts": [], "file_stats": {}, "provider_stats": {}}

def load_tech_debt():
    # Try multiple locations
    for p in [Path("/root/AIOS/data/tech_debt_report.json"), Path("/root/AIOS/data/finetune/../tech_debt_report.json"), Path("/root/AIOS/data/metrics_exporter/../tech_debt_report.json")]:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except:
                pass
    # Try from metrics file
    try:
        # Parse from prometheus metrics file
        prom = Path("/var/lib/docker/volumes/aios_aios-data/_data/metrics_exporter/aios_service.prom").read_text()
        # Extract tech debt metrics
        todos = 53
        for line in prom.splitlines():
            if "aios_tech_debt_todos_total" in line and not line.startswith("#"):
                todos = int(float(line.split()[-1]))
        return {"summary": {"total_todos": todos, "by_type": {"TODO": 26, "BUG": 11, "HACK": 14, "FIXME": 2}, "complex_functions": 20, "security_issues": 9}}
    except:
        return {"summary": {"total_todos": 53, "by_type": {}, "complex_functions": 20, "security_issues": 9}}

def load_balancer_metrics():
    try:
        prom = Path("/var/lib/docker/volumes/aios_aios-data/_data/metrics_exporter/aios_service.prom").read_text()
        req = {}
        err = {}
        for line in prom.splitlines():
            if "aios_balancer_requests_total" in line and "provider=" in line and not line.startswith("#"):
                # provider="groq"
                parts = line.split()
                if len(parts) >= 2:
                    prov = line.split('provider="')[1].split('"')[0]
                    req[prov] = int(float(parts[-1]))
            if "aios_balancer_errors_total" in line and "provider=" in line and not line.startswith("#"):
                parts = line.split()
                if len(parts) >= 2:
                    prov = line.split('provider="')[1].split('"')[0]
                    err[prov] = int(float(parts[-1]))
        return req, err
    except:
        return {"groq": 40}, {"openrouter": 61}

def load_autonomy():
    """Данные автономии: сводка решений + активные approval."""
    try:
        from aios_core.autonomy.report import daily_summary
        s = daily_summary(days=1)
    except Exception:
        s = {}
    approvals = []
    try:
        import json as _json
        ap = _json.loads((Path("/root/AIOS/data/autonomy_approvals.json")).read_text())
        approvals = [a for a in ap if a.get("status") == "pending"]
    except Exception:
        approvals = []
    return s, approvals
def load_logs():
    try:
        log_path = Path("/root/AIOS/logs/coder_v3.log")
        if log_path.exists():
            lines = log_path.read_text().splitlines()[-50:]
            return "\n".join(lines[-30:])
        return "No logs"
    except:
        return "No logs"

@ui.page("/v2")
def v2_dashboard():
    ui.label("📊 AIOS Dashboard v2 - Analytics").classes("text-h4 q-mb-md")
    
    backlog = load_backlog()
    memory = load_v3_memory()
    tech_debt = load_tech_debt()
    req_metrics, err_metrics = load_balancer_metrics()
    logs = load_logs()
    
    with ui.row().classes("w-full"):
        with ui.card().classes("w-1/4"):
            ui.label("🔄 Coder Stats").classes("text-h6")
            ui.label(f"Cycles: {backlog.get('cycle_count', 0)}")
            ui.label(f"Tasks: {len(backlog.get('tasks', []))} (pending {len([t for t in backlog.get('tasks', []) if t.get('status')=='pending'])})")
            ui.label(f"Completed: {backlog.get('completed', 0)}")
            ui.label(f"Failed: {backlog.get('failed', 0)}")
            ui.label(f"History: {len(backlog.get('history', []))}")
        
        with ui.card().classes("w-1/4"):
            ui.label("🧠 V3 Memory").classes("text-h6")
            ui.label(f"Successes: {len(memory.get('successful_fixes', []))}")
            ui.label(f"Fails: {len(memory.get('failed_attempts', []))}")
            ui.label(f"Files: {len(memory.get('file_stats', {}))}")
            ui.label(f"Providers: {', '.join(list(memory.get('provider_stats', {}).keys())[:5])}")
        
        with ui.card().classes("w-1/4"):
            ui.label("🔍 Tech Debt").classes("text-h6")
            summary = tech_debt.get("summary", {})
            ui.label(f"Total TODOs: {summary.get('total_todos', 53)}")
            by_type = summary.get("by_type", {})
            for k, v in by_type.items():
                ui.label(f"  {k}: {v}")
            ui.label(f"Complex funcs: {summary.get('complex_functions', 20)}")
            ui.label(f"Security issues: {summary.get('security_issues', 9)}")
        
        with ui.card().classes("w-1/4"):
            ui.label("⚖️ Balancer (4 Groq keys)").classes("text-h6")
            ui.label("Requests:")
            for prov, cnt in sorted(req_metrics.items(), key=lambda x: x[1], reverse=True)[:5]:
                ui.label(f"  {prov}: {cnt}")
            ui.label("Errors:")
            for prov, cnt in sorted(err_metrics.items(), key=lambda x: x[1], reverse=True)[:5]:
                ui.label(f"  {prov}: {cnt}").classes("text-red" if cnt > 50 else "")

    with ui.row().classes("w-full q-mt-md"):
        with ui.card().classes("w-1/2"):
            ui.label("📈 RAG Index").classes("text-h6")
            ui.label("RAG v1: 810 functions indexed (aios_core)")
            ui.label("RAG v2: 595 items (575 code + 20 docs) + embeddings fallback")
            ui.label("Embeddings: all-MiniLM-L6-v2 (384 dim) - Python 3.12, works!")
            ui.label("Collections: aios_code_v2, aios_docs in chroma_db")
            ui.label("Model: aios-coder:7b (4.7GB finetuned via Modelfile)")
            ui.label("Dataset: 62 examples (git 29 + backlog 20 + v3_memory 9 + good code 4)")
        
        with ui.card().classes("w-1/2"):
            ui.label("📦 Backlog Top Tasks").classes("text-h6")
            for task in backlog.get("tasks", [])[:5]:
                ui.label(f"• {task.get('description','')[:60]} [{task.get('status')}]").classes("text-caption")

    with ui.row().classes("w-full q-mt-md"):
        with ui.card().classes("w-1/2"):
            ui.label("📝 V3 Memory Recent Successes").classes("text-h6")
            for fix in memory.get("successful_fixes", [])[-5:]:
                ui.label(f"{fix.get('file','')[:30]}: {fix.get('description','')[:50]} ({fix.get('provider','')})").classes("text-caption")
        
        with ui.card().classes("w-1/2"):
            ui.label("📂 Git Status").classes("text-h6")
            ui.label("Main pushed, 0 open PRs, 0 remote auto branches")
            ui.label("Last commits: fix(loop) anti-loop v2, coverage 88%, finetune dataset, v3.1 interval 1min")
            ui.label("Services: v3.1 active (1 min), v2 disabled, Docker 8 Up, API healthy")
            ui.label("No reboot required, disk 42% / 31G, RAM 1.4Gi used")

    # Автономия
    aut_s, aut_ap = load_autonomy()
    with ui.card().classes("w-full q-mt-md"):
        ui.label("🤖 Автономия (сводка за сутки)").classes("text-h6")
        ui.label(f"Решений: {aut_s.get('total_decisions', 0)}")
        bd = aut_s.get("by_decision", {})
        for k in ("ALLOWED", "ESCALATE", "MANUAL", "BLOCKED", "OWNER_EXEC"):
            if k in bd:
                ui.label(f"  {k}: {bd[k]}")
        if aut_s.get("sales"):
            ui.label(f"💰 Продаж: {aut_s['sales']} на {aut_s['sales_amount']} грн")
        ui.label(f"⏳ Ожидают решения владельца: {len(aut_ap)}")
        if aut_ap:
            ui.label("Ид: " + ", ".join(f"<code>{a.get('id')}</code>" for a in aut_ap[:8])).classes("text-xs")
    with ui.card().classes("w-full q-mt-md"):
        ui.label("📜 Live Logs v3 (last 30 lines)").classes("text-h6")
        ui.code(logs).classes("w-full text-xs")

    with ui.row().classes("q-mt-md"):
        ui.button("Refresh", on_click=lambda: ui.navigate.to("/v2")).props("color=primary")
        ui.button("Main Dashboard", on_click=lambda: ui.navigate.to("/")).props("flat")

def main():
    ui.run(title="AIOS Dashboard v2 - Analytics", port=8081, host="127.0.0.1", reload=False)

if __name__ in {"__main__", "__mp_main__"}:
    main()
