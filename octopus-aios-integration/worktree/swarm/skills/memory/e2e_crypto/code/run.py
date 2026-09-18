#!/usr/bin/env python3
from pathlib import Path
import sys
import json
sys.path.insert(0, str(Path(__file__).resolve().parent))
from crypto_server import HAS_CRYPTOGRAPHY

def run(arg: str = '') -> dict:
    status = 'healthy' if HAS_CRYPTOGRAPHY else 'degraded'
    score = 1000 if HAS_CRYPTOGRAPHY else 600
    return {
        'skill': 'e2e_crypto',
        'timestamp': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        'score': score,
        'grade': 'S' if score >= 950 else 'A' if score >= 900 else 'B' if score >= 800 else 'C',
        'status': status,
        'has_cryptography': HAS_CRYPTOGRAPHY,
    }

if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
