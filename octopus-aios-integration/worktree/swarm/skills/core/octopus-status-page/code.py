import subprocess
import os
import json
from datetime import datetime

OUTPUT_PATH = '/var/www/octopus-uploader/status_lite.html'
REPUTATION_DB = '/var/lib/octopus/reputation.json'

def get_node_power(score):
    return round(1.0 + (score / 100.0), 2)

def generate_status_page():
    status = subprocess.check_output(['octopus', 'status'], text=True)
    
    reputation_html = "<h3>🏆 Node Leaderboard & Voting Power</h3><table style='width:100%; border-collapse: collapse;'>"
    reputation_html += "<tr style='border-bottom: 1px solid #444;'><th>Node</th><th>Score</th><th>Power</th><th>Uptime</th></tr>"
    
    if os.path.exists(REPUTATION_DB):
        with open(REPUTATION_DB, 'r') as f:
            data = json.load(f)
            sorted_nodes = sorted(data.items(), key=lambda x: x[1]['score'], reverse=True)
            for node, info in sorted_nodes:
                power = get_node_power(info['score'])
                reputation_html += f"<tr><td>{node}</td><td style='color:#00ff00'>{info['score']}</td><td style='color:#007bff'>x{power}</td><td>{info.get('uptime_hours',0)}h</td></tr>"
    reputation_html += "</table>"

    html = f"""
    <html>
    <head><title>Octopus Status Lite</title><meta http-equiv='refresh' content='60'></head>
    <body style='font-family: monospace; background: #121212; color: #00ff00; padding: 20px;'>
        <h2>🐙 Octopus System Status</h2>
        <p>Generated: {datetime.now().isoformat()}</p>
        <div style='display: flex; gap: 20px;'>
            <div style='flex: 2;'>
                <pre style='background: #1e1e1e; padding: 15px; border-radius: 5px;'>{status}</pre>
            </div>
            <div style='flex: 1; background: #1e1e1e; padding: 15px; border-radius: 5px;'>
                {reputation_html}
            </div>
        </div>
    </body>
    </html>
    """
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        f.write(html)
    print(f'Status page updated with Voting Power at {OUTPUT_PATH}')

if __name__ == '__main__':
    generate_status_page()
