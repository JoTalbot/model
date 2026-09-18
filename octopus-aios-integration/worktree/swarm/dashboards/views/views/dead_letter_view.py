# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
from nicegui import ui


def render_dead_letter_view():
    ui.label("Dead Letter Queue").classes("text-h4 q-mb-md")
    ui.label("Failed webhook messages that exceeded retry limit").classes("text-grey q-mb-md")

    ui.table(
        columns=[
            {"name": "id", "label": "ID", "field": "id"},
            {"name": "platform", "label": "Platform", "field": "platform"},
            {"name": "error", "label": "Error", "field": "error"},
            {"name": "timestamp", "label": "Timestamp", "field": "timestamp"},
            {"name": "actions", "label": "Actions", "field": "actions"},
        ],
        rows=[
            {
                "id": "1",
                "platform": "instagram",
                "error": "Connection timeout",
                "timestamp": "2026-07-27 10:30:00",
                "actions": "retry",
            },
            {
                "id": "2",
                "platform": "olx",
                "error": "Invalid signature",
                "timestamp": "2026-07-27 11:15:00",
                "actions": "retry",
            },
        ],
        row_key="id",
    ).classes("w-full")

    ui.button("Refresh", on_click=lambda: ui.notify("Refreshing...")).classes("q-mt-md")
