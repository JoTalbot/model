# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
from nicegui import ui


def render_jobs_dashboard_view():
    ui.label("Background Jobs Dashboard").classes("text-h4 q-mb-md")
    with ui.row().classes("w-full gap-4"):
        with ui.card().classes("flex-1"):
            ui.label("Active").classes("text-h6")
            ui.label("3").classes("text-h3 text-primary")
        with ui.card().classes("flex-1"):
            ui.label("Completed (24h)").classes("text-h6")
            ui.label("142").classes("text-h3 text-positive")
        with ui.card().classes("flex-1"):
            ui.label("Failed").classes("text-h6")
            ui.label("2").classes("text-h3 text-negative")
    ui.table(
        columns=[
            {"name": "id", "label": "Job ID", "field": "id"},
            {"name": "name", "label": "Task", "field": "name"},
            {"name": "status", "label": "Status", "field": "status"},
        ],
        rows=[
            {"id": "job_1", "name": "process_competitor_prices", "status": "running"},
            {"id": "job_2", "name": "send_bulk_messages", "status": "completed"},
            {"id": "job_3", "name": "long_llm_request", "status": "failed"},
        ],
        row_key="id",
    ).classes("w-full")
    ui.button("Refresh", on_click=lambda: ui.notify("Refreshing...")).classes("q-mt-md")
