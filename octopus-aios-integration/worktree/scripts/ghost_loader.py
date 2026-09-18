
import os
import sys
import subprocess
import time
import socket
from pathlib import Path

# === IMMORTAL CONFIG ===
REPO_URL = "https://github.com/JoTalbot/octopus.git"
INSTALL_DIR = Path("/opt/octopus")
SERVICE_NAME = "octopus-immortal"

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def setup():
    print("🐙 [1/4] Подготовка системы...")
    run("apt-get update && apt-get install -y git python3-pip tor docker.io docker-compose")
    
    print("🐙 [2/4] Клонирование Бессмертного Роя...")
    if INSTALL_DIR.exists():
        run(f"rm -rf {INSTALL_DIR}")
    run(f"git clone {REPO_URL} {INSTALL_DIR}")
    
    print("🐙 [3/4] Настройка Tor Hidden Service (Вход без портов)...")
    torrc = """
HiddenServiceDir /var/lib/tor/octopus_service/
HiddenServicePort 80 127.0.0.1:9100
"""
    with open("/etc/tor/torrc", "a") as f:
        f.write(torrc)
    run("systemctl restart tor")
    time.sleep(5) # Ждем генерации адреса
    
    try:
        with open("/var/lib/tor/octopus_service/hostname", "r") as f:
            onion_addr = f.read().strip()
    except:
        onion_addr = "Генерируется... Посмотри позже в /var/lib/tor/octopus_service/hostname"

    print("🐙 [4/4] Запуск Docker-контейнера с Админкой...")
    os.chdir(INSTALL_DIR)
    
    # Создаем Dockerfile на лету для максимальной совместимости
    dockerfile = """
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "node.py", "start", "--port", "8000"]
"""
    with open("Dockerfile", "w") as f: f.write(dockerfile)
    
    run("docker build -t octopus-node .")
    run("docker run -d --name octopus --network host --restart always octopus-node")

    # Создаем скрипт самолечения
    with open(f"/etc/systemd/system/{SERVICE_NAME}.service", "w") as f:
        f.write(f"""[Unit]
Description=Octopus Immortal Node
After=network.target tor.service

[Service]
ExecStart=/usr/bin/python3 {INSTALL_DIR}/node.py start
Restart=always
WorkingDirectory={INSTALL_DIR}

[Install]
WantedBy=multi-user.target
""")
    run("systemctl daemon-reload && systemctl enable octopus-immortal")

    print("\n" + "="*50)
    print("🚀 УЗЕЛ СТАЛ БЕССМЕРТНЫМ!")
    print(f"Твой секретный адрес для Tor Browser:")
    print(f"🔗 http://{onion_addr}")
    print("="*50)
    print("Теперь ты можешь закрыть SSH и управлять всем через этот адрес.")

if __name__ == "__main__":
    if os.getuid() != 0:
        print("Ошибка: Запусти через sudo!")
        sys.exit(1)
    setup()
