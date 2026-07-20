#!/usr/bin/env python3
"""Fetch all starred repos from GitHub API using gh CLI with pagination."""
import subprocess, json, sys, os

def fetch_starred_repos(gh_pat):
    """Fetch all starred repos using gh CLI with pagination."""
    all_repos = []
    page = 1
    while True:
        result = subprocess.run([
            'gh', 'api', f'user/starred?per_page=100&page={page}',
            '-q', '.'
        ], capture_output=True, text=True, env={**dict(os.environ), 'GH_TOKEN': gh_pat})
        
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
    
    return all_repos

def main():
    gh_pat = os.environ.get('GH_PAT')
    if not gh_pat:
        print("Error: GH_PAT environment variable not set", file=sys.stderr)
        sys.exit(1)
    
    os.makedirs('data', exist_ok=True)
    
    print("Fetching starred repos...")
    all_repos = fetch_starred_repos(gh_pat)
    
    with open('data/starred_raw.json', 'w') as f:
        json.dump(all_repos, f, indent=2)
    
    print(f"Total fetched: {len(all_repos)} repos")

if __name__ == '__main__':
    main()