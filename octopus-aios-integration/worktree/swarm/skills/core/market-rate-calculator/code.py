import json
import os

RATES_FILE = '/var/lib/octopus/market_rates.json'

def convert(resource, amount):
    if not os.path.exists(RATES_FILE): return amount
    with open(RATES_FILE, 'r') as f: rates = json.load(f)['rates']
    rate = rates.get(resource, 1.0)
    value = amount * rate
    print(f'[ECONOMY] {amount} {resource} = {value} Swarm-Credits (Rate: {rate})')
    return value

if __name__ == '__main__':
    convert('whisper_hour', 5)
