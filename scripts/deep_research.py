#!/usr/bin/env python3
"""
Deep research on all starred repos:
- Fetch README
- Fetch key config files (package.json, requirements.txt, Cargo.toml, go.mod, etc.)
- Fetch releases, contributors, languages
- Deep LLM analysis with full context
- Handles rate limits with exponential backoff
"""
import os, json, time, hashlib, sys, subprocess
from pathlib import Path
import requests

GITHUB_API = "https://api.github.com"
NVIDIA_API = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "meta/llama-3.1-70b-instruct"

DATA_DIR = Path(__file__).parent.parent / "data"
DEEP_CACHE = DATA_DIR / "deep_research.json"
STARRED_RAW = DATA_DIR / "starred_raw.json"

# Key files to fetch for code analysis
KEY_FILES = [
    "README.md", "README.rst", "README.txt",
    "package.json", "requirements.txt", "pyproject.toml", "setup.py",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "composer.json",
    "Dockerfile", "docker-compose.yml", ".github/workflows/ci.yml",
    "tsconfig.json", "pyrightconfig.json", "mypy.ini",
]

DEEP_PROMPT = """You are a senior software architect. Analyze this GitHub repository deeply.

Repository: {full_name}
Description: {description}
Language: {language}
Stars: {stargazers_count}
Topics: {topics}

README (truncated):
{readme}

Key Files:
{key_files}

Provide a JSON object with:
{{
  "inferred_topics": ["topic1", "topic2", ...],  // 5-10 specific use-case topics (kebab-case)
  "primary_purpose": "one-sentence summary of what this repo does",
  "tech_stack": ["tech1", "tech2", ...],  // frameworks, libraries, cloud services
  "architecture_patterns": ["pattern1", ...],  // e.g., "microservices", "event-driven", "plugin-system"
  "use_cases": ["use-case1", ...],  // concrete problems it solves
  "maturity": "experimental|active|stable|deprecated",
  "target_audience": "developers|data-scientists|devops|researchers|general",
  "unique_value": "what makes this different from alternatives",
  "dependencies": ["dep1", "dep2", ...],  // key external dependencies
  "complexity_score": 1-10,  // codebase complexity
  "production_ready": true/false
}}

Return ONLY valid JSON. No markdown, no explanations."""

def gh_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "star-graph-deep-research"}

def nvidia_headers(key):
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "Vibe-Trading/1.0"}

def fetch_with_backoff(url, headers, max_retries=5, base_delay=2):
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 403 and "rate limit" in r.text.lower():
                delay = base_delay * (2 ** attempt) + 60
                print(f"  Rate limited, waiting {delay}s...")
                time.sleep(delay)
                continue
            elif r.status_code == 404:
                return None
            else:
                print(f"  HTTP {r.status_code}: {r.text[:100]}")
                if r.status_code >= 500:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
                return None
        except Exception as e:
            print(f"  Error: {e}, retrying...")
            time.sleep(base_delay * (2 ** attempt))
    return None

def fetch_repo_contents(owner_repo, token, path=""):
    url = f"{GITHUB_API}/repos/{owner_repo}/contents/{path}"
    return fetch_with_backoff(url, gh_headers(token))

def fetch_file_content(owner_repo, token, path):
    url = f"{GITHUB_API}/repos/{owner_repo}/contents/{path}"
    data = fetch_with_backoff(url, gh_headers(token))
    if data and "content" in data:
        import base64
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")[:5000]
        except:
            return ""
    return ""

def fetch_readme(owner_repo, token):
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        content = fetch_file_content(owner_repo, token, name)
        if content:
            return content[:10000]
    return ""

def fetch_key_files(owner_repo, token):
    """Fetch key files using tree API to avoid 404s on non-existent files."""
    files = {}
    # Use tree API to find which key files actually exist (1 API call instead of 17)
    tree_data = fetch_with_backoff(
        f"{GITHUB_API}/repos/{owner_repo}/git/trees/HEAD?recursive=1",
        gh_headers(token)
    )
    existing_paths = set()
    if tree_data and "tree" in tree_data:
        existing_paths = {item["path"] for item in tree_data["tree"] if item["type"] == "blob"}
    
    for fname in KEY_FILES:
        if fname not in existing_paths:
            continue
        content = fetch_file_content(owner_repo, token, fname)
        if content:
            files[fname] = content[:3000]
        time.sleep(0.1)
    return files

def fetch_releases(owner_repo, token):
    url = f"{GITHUB_API}/repos/{owner_repo}/releases?per_page=5"
    data = fetch_with_backoff(url, gh_headers(token))
    if data:
        return [{"tag": r["tag_name"], "name": r["name"], "body": (r["body"] or "")[:2000], "prerelease": r["prerelease"], "date": r["published_at"]} for r in data]
    return []

def fetch_languages(owner_repo, token):
    url = f"{GITHUB_API}/repos/{owner_repo}/languages"
    return fetch_with_backoff(url, gh_headers(token)) or {}

def fetch_contributors(owner_repo, token):
    url = f"{GITHUB_API}/repos/{owner_repo}/contributors?per_page=10"
    data = fetch_with_backoff(url, gh_headers(token))
    if data:
        return [{"login": c["login"], "contributions": c["contributions"]} for c in data]
    return []

def compute_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

def deep_analyze(repo, readme, key_files, releases, languages, contributors, api_key):
    prompt = DEEP_PROMPT.format(
        full_name=repo["full_name"],
        description=repo.get("description", "No description"),
        language=repo.get("language", "Unknown"),
        stargazers_count=repo.get("stargazers_count", 0),
        topics=repo.get("topics", []),
        readme=readme[:8000] if readme else "No README",
        key_files=json.dumps(key_files, indent=2)[:5000] if key_files else "None"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a senior software architect. Output ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1500,
        "temperature": 0.1
    }
    for attempt in range(3):
        try:
            r = requests.post(NVIDIA_API, headers=nvidia_headers(api_key), json=payload, timeout=120)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                import re
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return json.loads(content)
            elif r.status_code == 429:
                delay = 30 * (2 ** attempt)
                print(f"  NVIDIA rate limit, waiting {delay}s...")
                time.sleep(delay)
            else:
                print(f"  NVIDIA error {r.status_code}: {r.text[:200]}")
                time.sleep(10 * (attempt + 1))
        except Exception as e:
            print(f"  LLM error: {e}")
            time.sleep(10)
    return {}

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="GitHub token")
    parser.add_argument("--nvidia-key", required=True, help="NVIDIA API key")
    parser.add_argument("--limit", type=int, default=0, help="Limit repos (0 = all)")
    parser.add_argument("--skip-cached", action="store_true", help="Skip repos with cached deep research")
    args = parser.parse_args()

    with open(STARRED_RAW) as f:
        repos = json.load(f)

    cache = {}
    if DEEP_CACHE.exists():
        with open(DEEP_CACHE) as f:
            cache = json.load(f)

    total = len(repos) if args.limit == 0 else min(args.limit, len(repos))
    print(f"Deep researching {total} repos...")

    for i, repo in enumerate(repos[:total] if args.limit else repos):
        full_name = repo["full_name"]
        print(f"\n[{i+1}/{total}] {full_name}")

        if args.skip_cached and full_name in cache and cache[full_name].get("deep_analysis"):
            print("  Cached, skipping")
            continue

        # Fetch all data
        print("  Fetching README...")
        readme = fetch_readme(full_name, args.token)

        print("  Fetching key files...")
        key_files = fetch_key_files(full_name, args.token)

        print("  Fetching releases...")
        releases = fetch_releases(full_name, args.token)

        print("  Fetching languages...")
        languages = fetch_languages(full_name, args.token)

        print("  Fetching contributors...")
        contributors = fetch_contributors(full_name, args.token)

        print("  Deep LLM analysis...")
        analysis = deep_analyze(repo, readme, key_files, releases, languages, contributors, args.nvidia_key)

        cache[full_name] = {
            "repo_hash": compute_hash(repo),
            "readme": readme[:5000],
            "key_files": {k: v[:1000] for k, v in key_files.items()},
            "releases": releases,
            "languages": languages,
            "contributors": contributors,
            "deep_analysis": analysis,
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

        # Periodic save
        if (i + 1) % 5 == 0:
            with open(DEEP_CACHE, "w") as f:
                json.dump(cache, f, indent=2)

        time.sleep(1)  # Be nice to APIs

    # Final save
    with open(DEEP_CACHE, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"\nDone! Saved {len(cache)} repos to {DEEP_CACHE}")

if __name__ == "__main__":
    main()
