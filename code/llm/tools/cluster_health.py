
import socket, json
NODES = [("arm-server-01", "10.0.0.3", 9600), ("octopus-micro-01", "10.0.0.2", 9400), ("octopus-micro-02", "10.0.0.87", 9400)]
def run():
    status = []
    for name, ip, port in NODES:
        try:
            with socket.create_connection((ip, port), timeout=1.0):
                status.append({"node": name, "ip": ip, "status": "UP", "port": port})
        except Exception:
            status.append({"node": name, "ip": ip, "status": "DOWN", "port": port})
    return status
