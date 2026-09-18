
import os
import time
import socket
import asyncio
import qrcode
import threading
import subprocess
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, HTTPServer
import httpx

# --- Configuration ---
WATCH_FOLDER = Path("./swarm_files")
WATCH_FOLDER.mkdir(exist_ok=True)
UPLOAD_PORT = 9200
DASHBOARD_PORT = 9100

# TELEGRAM (Fill these)
TELEGRAM_TOKEN = "" 
TELEGRAM_CHAT_ID = "" 

UPLOAD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Octopus Easy Sync</title>
    <style>
        body { font-family: sans-serif; background: #0e0e10; color: #e8e8ea; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #16161a; padding: 2rem; border-radius: 1rem; border: 1px solid #2a2a32; text-align: center; width: 80%; }
        button { background: #7dd3fc; color: #0e0e10; border: none; padding: 1rem; border-radius: 0.5rem; font-weight: bold; width: 100%; cursor: pointer; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🐙 Octopus Sync</h1>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" required><br><br>
            <button type="submit">ОТПРАВИТЬ</button>
        </form>
    </div>
</body>
</html>
"""

async def send_to_tg(fpath):
    if not TELEGRAM_TOKEN: return
    try:
        async with httpx.AsyncClient() as client:
            with open(fpath, "rb") as f:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                    data={"chat_id": TELEGRAM_CHAT_ID},
                    files={"document": f}
                )
    except: pass

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200); self.end_headers(); self.wfile.write(UPLOAD_HTML.encode())
        else: super().do_GET()
    def do_POST(self):
        from cgi import FieldStorage
        form = FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD':'POST', 'CONTENT_TYPE':self.headers['Content-Type']})
        if "file" in form:
            fname = os.path.basename(form["file"].filename)
            with open(WATCH_FOLDER / fname, "wb") as f: f.write(form["file"].file.read())
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(('8.8.8.8', 1)); ip = s.getsockname()[0]
    except: ip = '127.0.0.1'
    finally: s.close()
    return ip

async def watch():
    known = set(os.listdir(WATCH_FOLDER))
    while True:
        current = set(os.listdir(WATCH_FOLDER))
        for f in (current - known):
            fpath = WATCH_FOLDER / f
            if fpath.is_file():
                print(f"[+] Syncing file to Swarm: {f}")
                # Use 'note add' as the universal sync command
                subprocess.run(["python3", "node.py", "note", "add", f"File synced: {f}", "--tag", "sync", "--title", f])
                await send_to_tg(fpath)
        known = current
        await asyncio.sleep(2)

async def main():
    ip = get_ip()
    print(f"\n🐙 СЕТЬ ЗАПУЩЕНА\nURL: http://{ip}:{UPLOAD_PORT}\nDashboard: http://{ip}:{DASHBOARD_PORT}\n")
    qr = qrcode.QRCode()
    qr.add_data(f"http://{ip}:{UPLOAD_PORT}")
    qr.print_ascii()
    
    # Start swarm node
    subprocess.Popen(["python3", "node.py", "start", "--port", "8000"])
    
    # Start upload server
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', UPLOAD_PORT), Handler).serve_forever(), daemon=True).start()
    
    await watch()

if __name__ == "__main__":
    asyncio.run(main())
