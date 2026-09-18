# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
"""NiceGUI View for AI Advisor Template Management."""

from nicegui import ui


def render_advisor_templates_view(template_engine):
    """Отрисовка страницы управления шаблонами AI Advisor."""

    ui.label("🤖 Управление шаблонами AI Advisor").classes("text-h4 q-mb-md")

    columns = [
        {"name": "name", "label": "Название", "field": "name", "align": "left"},
        {"name": "intent", "label": "Намерение", "field": "intent", "align": "left"},
        {"name": "platform", "label": "Платформа", "field": "platform", "align": "left"},
        {"name": "actions", "label": "Действия", "field": "actions", "align": "right"},
    ]

    def get_rows():
        return [t.to_dict() for t in template_engine.list_templates()]

    table = ui.table(columns=columns, rows=get_rows(), row_key="id").classes("w-full")

    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label("Новый шаблон").classes("text-h6")

        name_input = ui.input("Название").props("outlined").classes("w-full")
        intent_input = (
            ui.select(
                label="Намерение (Intent)",
                options=[
                    "greeting",
                    "price_inquiry",
                    "delivery_question",
                    "stock_check",
                    "complaint",
                    "general_inquiry",
                ],
            )
            .props("outlined")
            .classes("w-full")
        )

        platform_input = (
            ui.select(
                label="Платформа (опционально)",
                options={
                    "": "Все платформы",
                    "olx": "OLX",
                    "prom": "Prom.ua",
                    "instagram": "Instagram",
                    "facebook": "Facebook",
                },
            )
            .props("outlined")
            .classes("w-full")
        )

        content_input = ui.textarea("Содержимое (Jinja2)").props("outlined rows=5").classes("w-full")
        content_input.tooltip("Используйте {{ variable }} для подстановки данных")

        variables_input = ui.textarea("Переменные (JSON)").props("outlined rows=3").classes("w-full")
        variables_input.value = '[{"name": "customer.name", "type": "string", "required": true}]'

        with ui.row().classes("w-full justify-end"):
            ui.button("Отмена", on_click=dialog.close).props("flat")

            def save_template():
                try:
                    import json

                    from aios_core.advisor.templates_engine import TemplateVariable

                    vars_obj = [TemplateVariable(**v) for v in json.loads(variables_input.value or "[]")]

                    template_engine.create_template(
                        name=name_input.value,
                        content=content_input.value,
                        intent=intent_input.value,
                        platform=platform_input.value or None,
                        variables=vars_obj,
                    )
                    ui.notify("Шаблон успешно создан!", type="positive")
                    table.rows = get_rows()
                    table.update()
                    dialog.close()
                except Exception as e:
                    ui.notify(f"Ошибка: {e!s}", type="negative")

            ui.button("Сохранить", on_click=save_template).props("unelevated color=primary")

    ui.button("➕ Добавить шаблон", on_click=dialog.open).classes("q-mb-md")

    with ui.expansion("🧪 Живой предпросмотр шаблона", icon="science").classes("w-full q-mt-md"):
        ui.label("Проверьте, как шаблон выглядит с реальными данными").classes("text-caption text-grey")

        test_template_id = (
            ui.select(label="Выберите шаблон", options={t.id: t.name for t in template_engine.list_templates()})
            .props("outlined")
            .classes("w-full")
        )

        test_context = ui.textarea("Контекст (JSON)").props("outlined rows=4").classes("w-full")
        test_context.value = (
            '{\n  "customer": {"name": "Иван"},\n  "product": {"title": "iPhone 15", "price": 30000}\n}'
        )

        preview_area = ui.markdown("**Результат будет здесь**").classes("w-full q-pa-md bg-grey-2 rounded")

        def run_preview():
            if not test_template_id.value:
                ui.notify("Выберите шаблон", type="warning")
                return
            try:
                import json

                context_dict = json.loads(test_context.value)
                rendered = template_engine.render(test_template_id.value, context_dict)
                preview_area.content = f"```text\n{rendered}\n```"
                ui.notify("Успешно отрендерено!", type="positive")
            except json.JSONDecodeError:
                ui.notify("Невалидный JSON в контексте", type="negative")
            except Exception as e:
                ui.notify(f"Ошибка рендеринга: {e!s}", type="negative")

        ui.button("▶ Запустить предпросмотр", on_click=run_preview).classes("q-mt-sm")
