#!/usr/bin/env python3
"""
Deep research on all starred repos:
- Fetch README + key config files
- Deep LLM analysis with full context
- Concurrent GitHub fetches with rate-limit handling
- Validates LLM output before caching
"""
import os, json, time, hashlib, sys, base64, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

sys.path.insert(0, str(Path(__file__).parent))
from graph_utils import validate_deep_analysis

GITHUB_API = "https://api.github.com"
NVIDIA_API = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "meta/llama-3.1-70b-instruct"

DATA_DIR = Path(__file__).parent.parent / "data"
DEEP_CACHE = DATA_DIR / "deep_research.json"
STARRED_RAW = DATA_DIR / "starred_raw.json"

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
  "inferred_topics": ["topic1", "topic2", ...],
  "primary_purpose": "one-sentence summary of what this repo does",
  "tech_stack": ["tech1", "tech2", ...],
  "architecture_patterns": ["pattern1", ...],
  "use_cases": ["use-case1", ...],
  "maturity": "experimental|active|stable|deprecated",
  "target_audience": "developers|data-scientists|devops|researchers|general",
  "unique_value": "what makes this different from alternatives",
  "dependencies": ["dep1", "dep2", ...],
  "complexity_score": 1-10,
  "production_ready": true/false
}}

Return ONLY valid JSON. No markdown, no explanations."""


def gh_headers():
    token = os.environ.get('GH_PAT') or os.environ.get('GH_TOKEN', '')
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "star-graph/1.0"
    }


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
                if r.status_code >= 500:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
                return None
        except Exception as e:
            print(f"  Error: {e}, retrying...")
            time.sleep(base_delay * (2 ** attempt))
    return None


def fetch_file_content(owner_repo, path):
    url = f"{GITHUB_API}/repos/{owner_repo}/contents/{path}"
    data = fetch_with_backoff(url, gh_headers())
    if data and "content" in data:
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")[:5000]
        except Exception:
            return ""
    return ""


def fetch_readme(owner_repo):
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        content = fetch_file_content(owner_repo, name)
        if content:
            return content[:10000]
    return ""


def fetch_key_files(owner_repo):
    """Fetch root listing first, then only request files that exist."""
    url = f"{GITHUB_API}/repos/{owner_repo}/contents/"
    listing = fetch_with_backoff(url, gh_headers())
    if not listing:
        return {}

    existing = {item['name'] for item in listing if isinstance(item, dict)}
    # Also check .github/workflows/
    wf_listing = fetch_with_backoff(
        f"{GITHUB_API}/repos/{owner_repo}/contents/.github/workflows", gh_headers()
    )
    if wf_listing:
        existing.update(f".github/workflows/{item['name']}" for item in wf_listing if isinstance(item, dict))

    files = {}
    for fname in KEY_FILES:
        base = fname.split('/')[-1]
        if base not in existing and fname not in existing:
            continue
        content = fetch_file_content(owner_repo, fname)
        if content:
            files[fname] = content[:3000]
        time.sleep(0.05)
    return files


def compute_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def deep_analyze(repo, readme, key_files, api_key):
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
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "star-graph/1.0"
    }
    for attempt in range(3):
        try:
            r = requests.post(NVIDIA_API, headers=headers, json=payload, timeout=120)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    raw = json.loads(match.group())
                else:
                    raw = json.loads(content)
                return validate_deep_analysis(raw)
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


def research_one(repo, api_key):
    """Research a single repo: fetch GitHub data concurrently, then LLM."""
    full_name = repo["full_name"]
    print(f"  Fetching GitHub data for {full_name}...")

    readme = ""
    key_files = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        readme_future = pool.submit(fetch_readme, full_name)
        keyfiles_future = pool.submit(fetch_key_files, full_name)
        readme = readme_future.result()
        key_files = keyfiles_future.result()

    print(f"  LLM analysis for {full_name}...")
    analysis = deep_analyze(repo, readme, key_files, api_key)

    return {
        "repo_hash": compute_hash(repo),
        "readme": readme[:5000],
        "key_files": {k: v[:1000] for k, v in key_files.items()},
        "deep_analysis": analysis,
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Limit repos (0 = all)")
    parser.add_argument("--skip-cached", action="store_true", help="Skip repos with cached deep research")
    args = parser.parse_args()

    api_key = os.environ.get('NVIDIA_API_KEY')
    if not api_key:
        print("Error: NVIDIA_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

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

        result = research_one(repo, api_key)
        cache[full_name] = result

        if (i + 1) % 5 == 0:
            with open(DEEP_CACHE, "w") as f:
                json.dump(cache, f, indent=2)

        time.sleep(1)

    with open(DEEP_CACHE, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"\nDone! Saved {len(cache)} repos to {DEEP_CACHE}")


if __name__ == "__main__":
    main()
