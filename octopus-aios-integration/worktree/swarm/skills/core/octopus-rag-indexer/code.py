import os
import json
import requests

RAG_URL = 'http://127.0.0.1:9555/index' # Assuming RAG API has /index
SKILLS_ROOT = '/root/agents/-Octopus/skills'

def index_skills():
    indexed = 0
    for root, dirs, files in os.walk(SKILLS_ROOT):
        if 'SKILL.md' in files:
            with open(os.path.join(root, 'SKILL.md'), 'r') as f:
                content = f.read()
                name = os.path.basename(root)
                # Simulated indexing call
                print(f'Indexing skill: {name}...')
                indexed += 1
    print(f'Total {indexed} skills prepared for RAG.')

if __name__ == '__main__':
    index_skills()
