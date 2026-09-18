import subprocess, json

def execute(action: str = "scan", profile: str = "primary", target_id: str = None) -> dict:
    """Scans or triggers Google account API key provisioning across AI platforms for primary or secondary profile."""
    try:
        cmd = ["/opt/aios-venv/bin/python3", "/opt/octopus/octopus-provider-provisioner.py", action, "--profile", profile]
        if target_id and action == "run-provider":
            cmd.extend(["--id", target_id])
        
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        try:
            data = json.loads(res.stdout.strip())
            return {"ok": True, "result": data}
        except Exception:
            return {"ok": True, "raw": res.stdout.strip(), "error": res.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    print(execute("scan", "secondary"))
