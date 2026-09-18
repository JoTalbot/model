# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
from nicegui import ui


def render_marketplace_view():
    ui.label("Plugin Marketplace").classes("text-h4 q-mb-md")
    ui.label("Discover and install extensions for your workspace").classes("text-grey q-mb-lg")

    plugins = [
        {
            "name": "Avito Adapter",
            "author": "AIOS Team",
            "rating": 4.8,
            "installs": 1200,
            "price": "Free",
            "desc": "Full integration with Avito.ru messaging",
        },
        {
            "name": "Advanced Analytics",
            "author": "DataCorp",
            "rating": 4.5,
            "installs": 450,
            "price": "$29/mo",
            "desc": "Deep dive metrics and predictive churn analysis",
        },
        {
            "name": "CRM Sync (HubSpot)",
            "author": "Integrations Inc",
            "rating": 4.9,
            "installs": 890,
            "price": "$49/mo",
            "desc": "Two-way sync with HubSpot contacts and deals",
        },
    ]

    with ui.row().classes("w-full gap-4 flex-wrap"):
        for p in plugins:
            with ui.card().classes("w-full md:w-1/3"):
                with ui.row().classes("w-full items-center"):
                    ui.icon("extension", size="2em", color="primary")
                    with ui.column().classes("flex-1"):
                        ui.label(p["name"]).classes("text-h6")
                        ui.label(f"by {p['author']}").classes("text-caption text-grey")

                ui.label(p["desc"]).classes("text-body2 q-my-sm")

                with ui.row().classes("w-full justify-between items-center q-mt-sm"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("star", color="amber").classes("text-sm")
                        ui.label(f"{p['rating']} ({p['installs']})").classes("text-caption")
                    ui.label(p["price"]).classes("text-h6 text-positive")

                ui.button("Install", icon="download").classes("w-full q-mt-sm").props("color=primary")
