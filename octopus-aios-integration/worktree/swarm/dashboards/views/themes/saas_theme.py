# REFERENCE ONLY (Wave 5, item 20): ported as-is from AIOS clean-code-production
# for future dashboard work. NOT imported by octopus code, NOT covered by CI.
# Reason: requires nicegui (not in prod venv)
from nicegui import ui


def apply_saas_theme():
    ui.add_head_html("""
    <style>
        :root {
            --primary: #6366f1;
            --secondary: #8b5cf6;
            --accent: #ec4899;
            --dark: #1e293b;
            --light: #f8fafc;
        }
        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .q-card {
            border-radius: 16px !important;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1) !important;
        }
        .q-btn {
            border-radius: 8px !important;
            text-transform: none !important;
            font-weight: 500 !important;
        }
        .q-page {
            padding: 24px !important;
        }
    </style>
    <link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' rel='stylesheet'>
    """)


def apply_dark_theme():
    ui.add_head_html("""
    <style>
        :root {
            --primary: #3b82f6;
            --secondary: #8b5cf6;
            --bg-dark: #0f172a;
            --bg-card: #1e293b;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
        }
        body {
            background-color: var(--bg-dark) !important;
            color: var(--text-primary) !important;
        }
        .q-card {
            background-color: var(--bg-card) !important;
            color: var(--text-primary) !important;
        }
    </style>
    """)
