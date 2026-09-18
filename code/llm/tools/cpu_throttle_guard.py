import os, time, psutil

def run(**kwargs):
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 4
    cpu_pct = psutil.cpu_percent(interval=0.1)
    cpu_times = psutil.cpu_times_percent(interval=0.1)
    
    return {
        "load_1m": round(load1, 2),
        "load_5m": round(load5, 2),
        "cpu_count": cpu_count,
        "cpu_percent_total": cpu_pct,
        "iowait_percent": getattr(cpu_times, 'iowait', 0.0),
        "is_throttled": (load1 / cpu_count) > 0.9,
        "status": "HEALTHY" if (load1 / cpu_count) < 0.8 else "HEAVY_LOAD"
    }
