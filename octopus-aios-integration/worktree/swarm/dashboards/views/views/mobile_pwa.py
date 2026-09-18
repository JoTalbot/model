# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
from nicegui import ui


def render_mobile_pwa_view():
    ui.add_head_html('<link rel="manifest" href="/static/manifest.json">')
    ui.add_head_html(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">'
    )
    ui.add_head_html('<meta name="apple-mobile-web-app-capable" content="yes">')
    ui.add_head_html('<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">')

    ui.label("AIOS Mobile").classes("text-h5 q-mb-md text-center")

    with ui.column().classes("w-full gap-4 q-pa-md"):
        with ui.card().classes("w-full"):
            ui.label("Pending Approvals").classes("text-h6")
            ui.badge("3", color="negative").classes("absolute-top-right")
            ui.label("OLX: Discount request").classes("text-caption")
            ui.separator()
            with ui.row().classes("w-full justify-between"):
                ui.button("Reject", color="negative").classes("w-1/2")
                ui.button("Approve", color="positive").classes("w-1/2")

        with ui.card().classes("w-full"):
            ui.label("Active Negotiations").classes("text-h6")
            ui.label("Session #492: Counter-offer sent").classes("text-caption")
            ui.linear_progress(0.7).classes("w-full q-mt-sm")

        with ui.card().classes("w-full"):
            ui.label("System Health").classes("text-h6")
            with ui.row().classes("w-full justify-between"):
                ui.label("API").classes("text-positive")
                ui.label("99.9%").classes("text-grey")


# Test cases
def test_render_mobile_pwa_view():
    # Arrange
    expected_output = """
    <link rel="manifest" href="/static/manifest.json">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <h5 class="text-h5 q-mb-md text-center">AIOS Mobile</h5>
    <div class="w-full gap-4 q-pa-md">
        <div class="w-full">
            <h6 class="text-h6">Pending Approvals</h6>
            <badge color="negative" absolute-top-right>3</badge>
            <p class="text-caption">OLX: Discount request</p>
            <hr>
            <row justify-between class="w-full">
                <button color="negative" class="w-1/2">Reject</button>
                <button color="positive" class="w-1/2">Approve</button>
            </row>
        </div>
        <div class="w-full">
            <h6 class="text-h6">Active Negotiations</h6>
            <p class="text-caption">Session #492: Counter-offer sent</p>
            <linear-progress value="0.7" class="w-full q-mt-sm"></linear-progress>
        </div>
        <div class="w-full">
            <h6 class="text-h6">System Health</h6>
            <row justify-between class="w-full">
                <span class="text-positive">API</span>
                <span class="text-grey">99.9%</span>
            </row>
        </div>
    </div>
    """

    # Act
    with ui.test_client() as client:
        response = client.get("/render_mobile_pwa_view")
        actual_output = response.text

    # Assert
    assert actual_output == expected_output, f"Expected output does not match actual output:\n{expected_output}\n\nActual output:\n{actual_output}"