
import json, subprocess
def run(query="Oracle Cloud Always Free"):
    res = subprocess.run(['sudo', 'python3', '/opt/octopus-skills-vectorizer.py', 'find', query], capture_output=True, text=True)
    try:
        return json.loads(res.stdout)
    except:
        return {"raw": res.stdout}
