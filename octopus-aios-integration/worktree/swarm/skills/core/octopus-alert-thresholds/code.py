import json
import os

CONFIG_PATH = '/run/octopus/alert_thresholds.json'

def adaptive_thresholds():
    # Load current system metrics (simulated logic)
    # In reality, this would read from Prometheus or local history
    base_config = {
        'disk_usage_percent': 90,
        'load_average_limit': 4.0,
        'nrestarts_limit': 50
    }
    
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(base_config, f, indent=2)
    print(f'Adaptive thresholds updated at {CONFIG_PATH}')

if __name__ == '__main__':
    adaptive_thresholds()
