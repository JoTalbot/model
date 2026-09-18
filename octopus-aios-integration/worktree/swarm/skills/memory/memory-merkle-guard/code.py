import hashlib
import os

def calculate_pool_hash(pool_path='/var/lib/octopus/packstore'):
    hashes = []
    for root, dirs, files in os.walk(pool_path):
        for f in sorted(files):
            p = os.path.join(root, f)
            with open(p, 'rb') as file:
                hashes.append(hashlib.sha256(file.read()).hexdigest())
    master_hash = hashlib.sha256(''.join(hashes).encode()).hexdigest()
    return master_hash

if __name__ == '__main__':
    print(f"Memory Pool Master Hash: {calculate_pool_hash()}")
