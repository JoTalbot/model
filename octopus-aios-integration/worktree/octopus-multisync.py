#!/usr/bin/env python3
"""
Octopus Multi-Master Active-Active Directory Synchronizer
Обеспечивает непрерывную P2P-синхронизацию проектных папок (~/agents,
/opt, /etc/octopus, /var/lib/octopus) между всеми запущенными нодами.

Позволяет пользователю подключаться к ЛЮБОМУ серверу кластера и вносить
правки — они мгновенно отражаются на всех остальных серверах.
"""

import os
import sys
import json
import time
import socket
import subprocess
from pathlib import Path

sys.path.append("/var/lib/octopus/clip-venv/lib/python3.10/site-packages")
from huggingface_hub import HfApi

CONFIG = {
    "HF_REPO_ID": "JoTalbot/octopus-eternal",
    "HF_TOKEN": "<HF_TOKEN_REDACTED>",
    "S3_BUCKET": "octopus-packstore-archive-2026",
    "LOCAL_NODES_FILE": "/etc/octopus/mesh_nodes.json",
    "SYNC_DIRS": [
        "/root/agents",
        "/etc/octopus",
        "/var/lib/octopus/wiki",
        "/var/lib/octopus/obsidian",
        "/var/lib/octopus/baselines",
        "/var/lib/octopus/runbooks",
        "/opt/octopus",
        "/opt/autosklo",
    ],
    "EXCLUDES": [
        "--exclude='*venv*'",
        "--exclude='node_modules'",
        "--exclude='.next'",
        "--exclude='backups'",
        "--exclude='memory_pool'",
        "--exclude='quarantine'",
        "--exclude='load_history.jsonl'",
        "--exclude='snapshots'",
        "--exclude='*.sock'",
        "--exclude='*.socket'",
        "--exclude='__pycache__'",
        "--exclude='.cache'",
        "--exclude='*.tmp'",
    ],
    "SYNC_INTERVAL_SEC": 60,
    "PEER_TIMEOUT_SEC": 20,
}

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] 🐙 MULTISYNC: {msg}")

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def get_my_ips():
    # Local IPs
    res = run_cmd("hostname -I")
    local_ips = res.stdout.strip().split()
    # Public IP
    pub_res = run_cmd("curl -4 -s --connect-timeout 5 https://ifconfig.me")
    pub_ip = pub_res.stdout.strip()
    return pub_ip, local_ips

def get_my_ssh_pubkey():
    key_path = "/root/.ssh/id_ed25519.pub"
    if not os.path.exists(key_path):
        run_cmd('ssh-keygen -t ed25519 -f /root/.ssh/id_ed25519 -N "" -C "octopus-node-$(hostname)"')
    with open(key_path, "r") as f:
        return f.read().strip()

def announce_and_discover_peers():
    pub_ip, local_ips = get_my_ips()
    pubkey = get_my_ssh_pubkey()
    hostname = socket.gethostname()
    now = int(time.time())
    
    my_info = {
        "hostname": hostname,
        "public_ip": pub_ip,
        "local_ips": local_ips,
        "ssh_pubkey": pubkey,
        "last_seen": now,
    }
    
    log(f"Анонсирование ноды: {hostname} ({pub_ip})...")
    
    # 1. Считываем и обновляем локальный mesh_nodes.json
    mesh_data = {}
    if os.path.exists(CONFIG["LOCAL_NODES_FILE"]):
        try:
            with open(CONFIG["LOCAL_NODES_FILE"], "r") as f:
                mesh_data = json.load(f)
        except Exception:
            pass
            
    mesh_data[pub_ip] = my_info
    
    # 2. Пытаемся скачать актуальный mesh_nodes.json с AWS S3
    s3_file = f"s3://{CONFIG['S3_BUCKET']}/discovery/mesh_nodes.json"
    aws_env = "export $(grep -v '^#' /etc/octopus/secrets.env | xargs)"
    res = run_cmd(f"{aws_env} && aws s3 cp {s3_file} /tmp/s3_mesh.json")
    if res.returncode == 0:
        try:
            with open("/tmp/s3_mesh.json", "r") as f:
                s3_data = json.load(f)
                for ip, info in s3_data.items():
                    # Объединяем, беря самые свежие last_seen
                    if ip not in mesh_data or info.get("last_seen", 0) > mesh_data[ip].get("last_seen", 0):
                        mesh_data[ip] = info
        except Exception:
            pass
            
    # Записываем объединенные данные
    os.makedirs(os.path.dirname(CONFIG["LOCAL_NODES_FILE"]), exist_ok=True)
    with open(CONFIG["LOCAL_NODES_FILE"], "w") as f:
        json.dump(mesh_data, f, indent=2)
        
    # Публикуем обратно в S3 и на HF
    run_cmd(f"{aws_env} && aws s3 cp {CONFIG['LOCAL_NODES_FILE']} {s3_file}")
    try:
        api = HfApi(token=CONFIG["HF_TOKEN"])
        api.upload_file(
            path_or_fileobj=CONFIG["LOCAL_NODES_FILE"],
            path_in_repo="discovery/mesh_nodes.json",
            repo_id=CONFIG["HF_REPO_ID"],
            repo_type="dataset",
        )
    except Exception as e:
        log(f"⚠️ Ошибка публикации mesh_nodes на HF: {e}")
        
    return mesh_data, pub_ip

def authorize_peer_keys(mesh_data, my_pub_ip):
    log("Проверка и авторизация SSH-ключей пиров...")
    auth_keys_path = "/root/.ssh/authorized_keys"
    
    existing_keys = set()
    if os.path.exists(auth_keys_path):
        with open(auth_keys_path, "r") as f:
            existing_keys = set(line.strip() for line in f if line.strip())
            
    added = 0
    for ip, info in mesh_data.items():
        key = info.get("ssh_pubkey")
        if key and key not in existing_keys:
            existing_keys.add(key)
            added += 1
            
    if added > 0:
        os.makedirs("/root/.ssh", exist_ok=True)
        with open(auth_keys_path, "w") as f:
            for k in sorted(existing_keys):
                f.write(k + "\n")
        os.chmod(auth_keys_path, 0o600)
        log(f"Успешно добавлено {added} новых SSH-ключей пиров в authorized_keys.")

def sync_with_peer(peer_ip):
    log(f"--- Запуск двунаправленной Active-Active синхронизации с {peer_ip} ---")
    
    # Пингуем пира перед тяжелым rsync
    res = run_cmd(f"ping -c 1 -W 2 {peer_ip}")
    if res.returncode != 0:
        log(f"⚠️ Пир {peer_ip} недоступен по ping, пропускаем.")
        return
        
    excludes = " ".join(CONFIG["EXCLUDES"])
    rsync_opts = "-avzu --no-perms --no-owner --no-group --timeout=30 --prune-empty-dirs"
    ssh_opts = "-e 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10'"
    
    # Поддержка IPv6 адресов (оборачиваем в квадратные скобки)
    peer_target = f"[{peer_ip}]" if ":" in peer_ip else peer_ip
    
    for sync_dir in CONFIG["SYNC_DIRS"]:
        if not os.path.exists(sync_dir):
            continue
            
        target_dir = sync_dir if sync_dir.endswith("/") else sync_dir + "/"
        
        # 1. PUSH: Отправляем наши более новые файлы пиру
        push_cmd = f"rsync {rsync_opts} {ssh_opts} {excludes} {target_dir} root@{peer_target}:{target_dir}"
        res = run_cmd(push_cmd)
        if res.returncode == 0:
            stdout_clean = '\n'.join([line for line in res.stdout.splitlines() if not line.startswith('sending') and not line.startswith('sent') and not line.startswith('total')])
            if stdout_clean.strip():
                log(f"✅ PUSH {sync_dir} -> {peer_ip}: Изменения синхронизированы.")
        else:
            log(f"⚠️ Ошибка PUSH {sync_dir} -> {peer_ip}: {res.stderr}")
            
        # 2. PULL: Забираем более новые файлы пира себе
        pull_cmd = f"rsync {rsync_opts} {ssh_opts} {excludes} root@{peer_target}:{target_dir} {target_dir}"
        res = run_cmd(pull_cmd)
        if res.returncode == 0:
            stdout_clean = '\n'.join([line for line in res.stdout.splitlines() if not line.startswith('receiving') and not line.startswith('sent') and not line.startswith('total')])
            if stdout_clean.strip():
                log(f"✅ PULL {peer_ip} -> {sync_dir}: Изменения получены.")
        else:
            log(f"⚠️ Ошибка PULL {peer_ip} -> {sync_dir}: {res.stderr}")

def main():
    if "--announce-only" in sys.argv:
        announce_and_discover_peers()
        print("Announce complete.")
        return
        
    log("=== ЗАПУСК ДЕМОНА MULTI-MASTER ACTIVE-ACTIVE СИНХРОНИЗАЦИИ ===")
    
    while True:
        try:
            start_t = time.time()
            mesh_data, my_pub_ip = announce_and_discover_peers()
            authorize_peer_keys(mesh_data, my_pub_ip)
            
            # Фильтруем пиров для синхронизации
            now = int(time.time())
            # fix(step_77): исключаем ВСЕ локальные адреса, а не только my_pub_ip
            try:
                _hi = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
            except Exception:
                _hi = []
            local_ips = set(_hi) | {my_pub_ip, "127.0.0.1", "::1"}
            try:
                import subprocess as _sp
                _ipr = _sp.run(["ip", "-o", "-4", "addr"], capture_output=True, text=True, timeout=5).stdout
                local_ips |= set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", _ipr))
            except Exception:
                pass
            active_peers = [
                ip for ip, info in mesh_data.items()
                if ip not in local_ips and (now - info.get("last_seen", 0)) < 86400  # видел за последние 24ч
            ]
            
            log(f"Активные удаленные пиры в рое: {active_peers}")
            
            for peer_ip in active_peers:
                sync_with_peer(peer_ip)
                
            elapsed = time.time() - start_t
            sleep_t = max(5, CONFIG["SYNC_INTERVAL_SEC"] - elapsed)
            log(f"Цикл синхронизации завершен за {elapsed:.1f} сек. Ожидание {sleep_t:.0f} сек...")
            time.sleep(sleep_t)
            
        except Exception as e:
            log(f"⚠️ Критическая ошибка в основном цикле MultiSync: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
