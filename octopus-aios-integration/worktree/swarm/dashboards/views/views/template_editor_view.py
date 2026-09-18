# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
import json

from nicegui import ui


def render_template_editor_view(template_engine):
    ui.label("🎨 Template Editor").classes("text-h4 q-mb-md")

    with ui.row().classes("w-full gap-4"):
        with ui.column().classes("w-1/2"):
            ui.label("Editor").classes("text-h6")
            name_input = ui.input("Template name").classes("w-full")
            intent_select = ui.select(
                label="Intent",
                options=[
                    "greeting",
                    "price_inquiry",
                    "delivery_question",
                    "stock_check",
                    "complaint",
                    "general_inquiry",
                ],
            ).classes("w-full")
            platform_select = ui.select(
                label="Platform", options={"": "All", "olx": "OLX", "prom": "Prom", "instagram": "Instagram"}
            ).classes("w-full")

            ui.label("Content (Jinja2):").classes("text-bold q-mt-md")
            content_area = ui.textarea().classes("w-full").props("rows=12 outlined")

            ui.label("Variables (JSON):").classes("text-bold q-mt-md")
            vars_area = ui.textarea().classes("w-full").props("rows=4 outlined")
            vars_area.value = json.dumps(
                [
                    {"name": "customer.name", "type": "string", "required": True},
                    {"name": "product.price", "type": "number", "required": True},
                ],
                indent=2,
            )

            with ui.row().classes("w-full gap-2 q-mt-md"):

                def save_template():
                    try:
                        from aios_core.advisor.templates_engine import TemplateVariable

                        variables = [TemplateVariable(**v) for v in json.loads(vars_area.value or "[]")]
                        template_engine.create_template(
                            name=name_input.value,
                            content=content_area.value,
                            intent=intent_select.value,
                            platform=platform_select.value or None,
                            variables=variables,
                        )
                        refresh_preview()
                    except Exception as e:
                        ui.notify(f"Error: {e}", type="negative")

                ui.button("💾 Save", on_click=save_template).props("color=primary")
                ui.button("🔄 Refresh Preview", on_click=refresh_preview).props("color=secondary")  # noqa: F821  # определён ниже в том же scope

        with ui.column().classes("w-1/2"):
            ui.label("Live Preview").classes("text-h6")
            ui.label("Test Context (JSON):").classes("text-bold")
            context_area = ui.textarea().classes("w-full").props("rows=6 outlined")
            context_area.value = json.dumps({"customer": {"name": "Ivan"}, "product": {"price": 1500}}, indent=2)

            ui.label("Rendered Output:").classes("text-bold q-mt-md")
            preview_area = ui.markdown("*Click Refresh to see preview*").classes("w-full q-pa-md bg-grey-2 rounded")

            def refresh_preview():
                try:
                    from aios_core.advisor.templates_engine import TemplateEngine

                    temp_engine = TemplateEngine(storage_path="/tmp/preview")
                    temp_tpl = temp_engine.create_template(name="preview", content=content_area.value, intent="preview")
                    ctx = json.loads(context_area.value or "{}")
                    temp_engine.render(temp_tpl.id, ctx)
                    preview_area.content = ""
                    temp_engine.delete_template(temp_tpl.id)
                except Exception as e:
                    preview_area.content = f"**Error:** {e}"

            ui.label("Syntax Help").classes("text-h6 q-mt-md")
            with ui.expansion("Show Jinja2 syntax").classes("w-full"):
                ui.markdown("""
- **Variable:** 
- **Condition:** 
- **Loop:** 
- **Filter:** 
""")
