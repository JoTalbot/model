# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
"""NiceGUI View for AI Advisor Metrics Dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from nicegui import ui


def render_metrics_view(metrics_collector):
    """Отрисовка дашборда метрик AI Advisor."""

    ui.label("📊 AI Advisor — Метрики и аналитика").classes("text-h4 q-mb-md")

    # Получаем сводку
    summary = metrics_collector.get_summary()

    # === Карточки с основными метриками ===
    with ui.row().classes("w-full gap-4 q-mb-lg"):
        with ui.card().classes("flex-1"):
            ui.label("📝 Черновики созданы").classes("text-caption")
            ui.label(str(summary["drafts_created"])).classes("text-h3 text-primary")

        with ui.card().classes("flex-1"):
            ui.label("✅ Approval Rate").classes("text-caption")
            ui.label(summary["approval_rate"]).classes("text-h3 text-positive")

        with ui.card().classes("flex-1"):
            ui.label("🚨 Эскалации").classes("text-caption")
            ui.label(str(summary["escalations"])).classes("text-h3 text-negative")

        with ui.card().classes("flex-1"):
            ui.label("🛡️ Нарушения").classes("text-caption")
            ui.label(str(summary["compliance_violations"])).classes("text-h3 text-warning")

    # === График: Топ намерений ===
    with ui.card().classes("w-full q-mb-lg"):
        ui.label("🎯 Топ намерений (Intents)").classes("text-h6")

        if summary["top_intents"]:
            intents_data = [{"name": intent, "count": count} for intent, count in summary["top_intents"]]

            ui.chart(
                series=[{"name": "Количество", "data": [d["count"] for d in intents_data]}],
                options={
                    "chart": {"type": "bar"},
                    "xaxis": {"categories": [d["name"] for d in intents_data]},
                    "colors": ["#1976D2"],
                    "plotOptions": {"bar": {"horizontal": False}},
                },
            ).classes("w-full h-64")
        else:
            ui.label("Нет данных").classes("text-grey")

    # === График: Распределение тональности ===
    with ui.card().classes("w-full q-mb-lg"):
        ui.label("😠 Распределение тональности").classes("text-h6")

        sentiment_data = summary["sentiment_distribution"]
        if any(sentiment_data.values()):
            ui.chart(
                series=[
                    {
                        "name": "Сообщения",
                        "data": [
                            sentiment_data.get("positive", 0),
                            sentiment_data.get("neutral", 0),
                            sentiment_data.get("negative", 0),
                        ],
                    }
                ],
                options={
                    "chart": {"type": "pie"},
                    "labels": ["Позитивные", "Нейтральные", "Негативные"],
                    "colors": ["#4CAF50", "#9E9E9E", "#F44336"],
                },
            ).classes("w-full h-64")
        else:
            ui.label("Нет данных").classes("text-grey")

    # === История за последние 7 дней ===
    with ui.card().classes("w-full"):
        ui.label("📅 История за 7 дней").classes("text-h6")

        history_data = []
        for i in range(7):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            metrics_file = Path(metrics_collector.storage_path) / f"{date}.json"
            if metrics_file.exists():
                data = json.loads(metrics_file.read_text())
                history_data.append(
                    {"date": date, "drafts": data.get("drafts_created", 0), "escalations": data.get("escalations", 0)}
                )

        if history_data:
            history_data.reverse()  # Хронологический порядок

            ui.chart(
                series=[
                    {"name": "Черновики", "data": [d["drafts"] for d in history_data]},
                    {"name": "Эскалации", "data": [d["escalations"] for d in history_data]},
                ],
                options={
                    "chart": {"type": "line"},
                    "xaxis": {"categories": [d["date"] for d in history_data]},
                    "colors": ["#1976D2", "#F44336"],
                    "stroke": {"curve": "smooth"},
                },
            ).classes("w-full h-64")
        else:
            ui.label("Нет данных за последние 7 дней").classes("text-grey")

    # === Кнопка обновления ===
    ui.button("🔄 Обновить", on_click=lambda: ui.navigate().reload()).classes("q-mt-md")
