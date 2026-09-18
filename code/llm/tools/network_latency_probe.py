import os, sys, subprocess, json, time, socket, math

def run(**kwargs):
    hosts = ["1.1.1.1", "8.8.8.8"]
    results = {}
    for host in hosts:
        if sys.platform.startswith("win"):
            cmd = ["ping", "-n", "4", "-w", "1000", host]
        else:
            cmd = ["ping", "-c", "4", "-W", "1", host]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            out = proc.stdout
            avg = None
            if sys.platform.startswith("win"):
                for line in out.splitlines():
                    if "Average =" in line:
                        parts = line.split("=")
                        if len(parts) == 2:
                            val = parts[1].strip()
                            if val.endswith("ms"):
                                val = val[:-2]
                            try:
                                avg = float(val)
                            except:
                                pass
            else:
                for line in out.splitlines():
                    if "rtt min/avg/max/mdev" in line or "round-trip min/avg/max/stddev" in line:
                        parts = line.split("=")
                        if len(parts) == 2:
                            stats = parts[1].strip().split("/")
                            if len(stats) >= 2:
                                try:
                                    avg = float(stats[1])
                                except:
                                    pass
            if avg is None:
                avg = float("nan")
        except Exception:
            avg = float("nan")
        results[host] = avg
    avg_all = sum(v for v in results.values() if not math.isnan(v)) / len(results)
    results["average"] = avg_all
    return results