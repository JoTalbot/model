import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'code'))
from run import run

def test_run():
    payload = run('')
    assert isinstance(payload, dict)
    assert payload['skill'] == 'pwa-file-exchange'
    print('OK')

if __name__ == '__main__':
    test_run()
