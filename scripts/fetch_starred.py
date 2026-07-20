#!/usr/bin/env python3
"""Fetch all starred repos for star-graph workflow."""
import subprocess, json, sys, os

# Fetch all pages
all_repos = []
page = 1
while True:
    result = subprocess.run([
        'gh', 'api', f'user/starred?per_page=100&page={page}',
        '-q', '.'
    ], capture_output=True, text=True, env={**dict(os.environ), 'GH_TOKEN': os.environ['GH_PAT']})
    
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    
    try:
        page_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        break
    
    if not page_data:
        break
        
    all_repos.extend(page_data)
    print(f"Page {page}: {len(page_data)} repos, total: {len(all_repos)}")
    page += 1

with open('data/starred_raw.json', 'w') as f:
    json.dump(all_repos, f, indent=2)
print(f"Total fetched: {len(all_repos)} repos")