# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
from nicegui import ui


def render_agents_chat_view(agent_orchestrator):
    ui.label("🤖 Multi-Agent Chat").classes("text-h4 q-mb-md")

    with ui.row().classes("w-full gap-4"):
        with ui.column().classes("w-1/3"):
            ui.label("Выберите агента:").classes("text-h6")
            agent_select = ui.select(
                label="Агент",
                options={
                    "auto": "🔄 Авто (маршрутизация)",
                    "sales": "💰 Sales Agent",
                    "support": "🛠️ Support Agent",
                    "analytics": "📊 Analytics Agent",
                },
            ).classes("w-full")
            agent_select.value = "auto"

            ui.label("История:").classes("text-h6 q-mt-md")
            history_area = ui.scroll_area().classes("w-full h-96 bg-grey-2 rounded q-pa-md")

        with ui.column().classes("w-2/3"):
            ui.label("Чат:").classes("text-h6")
            chat_area = ui.scroll_area().classes("w-full h-96 bg-grey-1 rounded q-pa-md")

            with ui.row().classes("w-full gap-2 q-mt-md"):
                message_input = ui.input(placeholder="Введите сообщение...").classes("flex-1")
                send_btn = ui.button("Отправить", on_click=None).props("color=primary")

            async def send_message():
                if not message_input.value:
                    return
                user_msg = message_input.value
                message_input.value = ""

                with chat_area:
                    ui.label(f"Вы: {user_msg}").classes("text-bold")

                messages = [user_msg]
                context = {"agent_mode": agent_select.value}

                if agent_select.value == "auto":
                    result = await agent_orchestrator.process(messages, context)
                else:
                    agent = agent_orchestrator.agents.get(agent_select.value)
                    from aios_core.agents.base import AgentState

                    state = AgentState(messages=messages, context=context, current_agent=agent_select.value)
                    state = await agent.process(state)
                    result = {"agent": state.current_agent, "result": state.result}

                with chat_area:
                    ui.label(f"[{result['agent']}]: {result['result']}").classes("text-positive")

                with history_area:
                    ui.label(f"→ {user_msg} [{result['agent']}]").classes("text-caption")

            send_btn.on_click(send_message)
            message_input.on("keydown.enter", send_message)
