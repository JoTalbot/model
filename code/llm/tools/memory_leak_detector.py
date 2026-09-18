import os
import json
import time
import subprocess
import math

def run(**kwargs):
    """
    Analyzes RSS memory consumption of octopus-* system services and detects anomalous growth.
    Returns a JSON-serializable dictionary with analysis results.
    """
    result = {
        "status": "success",
        "timestamp": time.time(),
        "services": [],
        "anomalies": [],
        "summary": {
            "total_services_checked": 0,
            "anomalies_detected": 0
        }
    }

    try:
        # Get list of octopus-* processes
        # Using ps to find processes matching octopus-*
        try:
            ps_output = subprocess.check_output(
                ["ps", "-eo", "pid,comm,rss"],
                stderr=subprocess.STDOUT,
                timeout=10
            ).decode('utf-8', errors='ignore')
        except Exception as e:
            result["status"] = "error"
            result["error_message"] = f"Failed to execute ps command: {str(e)}"
            return result

        lines = ps_output.strip().split('\n')
        if not lines:
            return result

        # Skip header
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            
            pid = parts[0]
            comm = parts[1]
            rss_kb_str = parts[2]
            
            # Filter for octopus-* services
            if not comm.startswith("octopus-"):
                continue
            
            try:
                rss_kb = int(rss_kb_str)
            except ValueError:
                continue
            
            # Basic anomaly detection logic:
            # Since we only have a single snapshot, we define "anomalous" based on absolute thresholds
            # or by comparing against a baseline if available in kwargs.
            # For this autonomous tool, we flag services with RSS > 100MB (102400 KB) as potentially anomalous
            # unless a specific threshold is provided in kwargs.
            
            threshold_mb = kwargs.get("threshold_mb", 100)
            threshold_kb = threshold_mb * 1024
            
            is_anomaly = rss_kb > threshold_kb
            
            service_info = {
                "pid": pid,
                "name": comm,
                "rss_kb": rss_kb,
                "rss_mb": round(rss_kb / 1024.0, 2),
                "is_anomaly": is_anomaly
            }
            
            result["services"].append(service_info)
            
            if is_anomaly:
                result["anomalies"].append({
                    "service": comm,
                    "pid": pid,
                    "rss_mb": service_info["rss_mb"],
                    "threshold_mb": threshold_mb,
                    "reason": f"RSS {service_info['rss_mb']}MB exceeds threshold {threshold_mb}MB"
                })

        result["summary"]["total_services_checked"] = len(result["services"])
        result["summary"]["anomalies_detected"] = len(result["anomalies"])

    except Exception as e:
        result["status"] = "error"
        result["error_message"] = str(e)

    return result