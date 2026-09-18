# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
from nicegui import ui


def render_evolution_view(evolution_orchestrator):
    ui.label("Evolution Dashboard").classes("text-h4 q-mb-md")

    with ui.row().classes("w-full gap-4"):
        with ui.card().classes("flex-1"):
            ui.label("Evolution Cycles").classes("text-h6")
            ui.label(str(len(evolution_orchestrator.log))).classes("text-h3 text-primary")

        with ui.card().classes("flex-1"):
            ui.label("Templates Evolved").classes("text-h6")
            total = sum(len(c.get("evolved", [])) for c in evolution_orchestrator.log)
            ui.label(str(total)).classes("text-h3 text-positive")

    ui.label("Evolution Log").classes("text-h6 q-mt-lg")

    if evolution_orchestrator.log:
        for cycle in reversed(evolution_orchestrator.log[-10:]):
            with ui.expansion(f"Cycle: {cycle.get('timestamp', 'unknown')}").classes("w-full"):
                ui.json(cycle)
    else:
        ui.label("No evolution cycles yet").classes("text-grey")

    async def run_cycle():
        result = await evolution_orchestrator.run_cycle()
        ui.notify(f"Evolution cycle completed: {len(result.get('evolved', []))} changes", type="positive")
        ui.navigate().reload()

    ui.button("Run Evolution Cycle Now", on_click=run_cycle).classes("q-mt-md").props("color=primary")
