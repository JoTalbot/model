#!/usr/bin/env python3
import os
import sys
import json
import time
import socket
import subprocess
from pathlib import Path

NODES_JSON = "/var/lib/octopus/nodes.json"
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TG_BOT_TOKEN", ""))
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] 🤖 AUTOHEAL: {msg}")

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def is_node_alive(ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.settimeout(2.0); res = sock.connect_ex((ip, 22)); sock.close(); return res == 0
    return ping_res.returncode == 0

def check_local_children():
    for p in range(8300, 8306):
        u = f"octopus-child@{p}.service"
        if os.system(f"systemctl is-active {u} > /dev/null") != 0:
            log(f"Restarting local child {u}...")
            os.system(f"systemctl start {u}")

def audit_and_decide():
    check_local_children()
    if not os.path.exists(NODES_JSON): return
    with open(NODES_JSON, "r") as f: nodes_data = json.load(f)
    
    changed = False
    for n in nodes_data.get("nodes", []):
        ip = n.get("public_ip")
        if not ip or ip == "127.0.0.1": continue
        alive = is_node_alive(ip)
        if alive and not n.get("enabled", True):
            log(f"Resurrecting {n['id']}")
            n["enabled"] = True
            n["status"] = "active"
            changed = True
        elif not alive and n.get("enabled", True):
            log(f"Node {n['id']} is DEAD")
            n["enabled"] = False
            n["status"] = "dead"
            changed = True
    
    if changed:
        with open(NODES_JSON, "w") as f: json.dump(nodes_data, f, indent=2)

if __name__ == "__main__":
    try:
        audit_and_decide()
    except Exception as e:
        log(f"Error: {e}")
