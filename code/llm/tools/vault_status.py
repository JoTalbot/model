
import json, subprocess
def run():
    res = subprocess.run(['sudo', 'python3', '/opt/octopus-oci-vault-sync.py', 'list'], capture_output=True, text=True)
    return res.stdout.strip()
