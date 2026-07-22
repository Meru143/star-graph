#!/usr/bin/env python3
"""
LLM enrichment pipeline for GitHub starred repos.
Calls NVIDIA NIM (Llama-3.1-70B-Instruct) to infer latent topics from repo metadata.
Uses NVIDIA_API_KEY env var (no CLI arg for secrets).
"""
import os, json, sys, time, hashlib, re
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from graph_utils import validate_inferred_topics

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "meta/llama-3.1-70b-instruct"

ENRICH_PROMPT = """Output ONLY a valid JSON array of 3-8 lowercase kebab-case topics for this GitHub repository.
No explanations, no markdown, no text - just the array.

Repo: {full_name}
Description: {description}
Language: {language}
Existing topics: {existing_topics}

JSON array:"""


def compute_hash(repo):
    mutable = f"{repo.get('description','')}|{json.dumps(repo.get('topics',[]), sort_keys=True)}|{repo.get('language','')}"
    return hashlib.sha256(mutable.encode()).hexdigest()[:16]


def call_nvidia_nim(repo, api_key, max_retries=5):
    prompt = ENRICH_PROMPT.format(
        full_name=repo.get('full_name', ''),
        description=repo.get('description', 'No description'),
        language=repo.get('language', 'Unknown'),
        existing_topics=repo.get('topics', [])
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "star-graph/1.0"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Output only valid JSON arrays. No text. No explanations."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 150,
        "temperature": 0.0
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content'].strip()
                match = re.search(r'\[.*?\]', content, re.DOTALL)
                if match:
                    topics = json.loads(match.group())
                    return validate_inferred_topics(topics)
                return []
            elif resp.status_code == 429:
                wait = (2 ** attempt) * 5
                print(f"  Rate limited (429), waiting {wait}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            else:
                print(f"API error {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
                if resp.status_code >= 500:
                    time.sleep((2 ** attempt) * 3)
                    continue
                return []
        except requests.exceptions.Timeout:
            print(f"  Timeout, retrying... (attempt {attempt+1}/{max_retries})")
            time.sleep((2 ** attempt) * 3)
        except Exception as e:
            print(f"Error calling NVIDIA NIM: {e}", file=sys.stderr)
            time.sleep((2 ** attempt) * 3)

    print(f"  Failed after {max_retries} retries", file=sys.stderr)
    return []


def enrich_repos(repos, api_key, cache_path):
    cache = {}
    if cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)

    enriched = {}
    total = len(repos)
    for i, repo in enumerate(repos):
        full_name = repo['full_name']
        repo_hash = compute_hash(repo)

        if full_name in cache and cache[full_name].get('hash') == repo_hash:
            enriched[full_name] = cache[full_name]
            if (i + 1) % 50 == 0:
                print(f"[{i+1}/{total}] Cache hit: {full_name}")
            continue

        print(f"[{i+1}/{total}] Enriching: {full_name}...")
        inferred = call_nvidia_nim(repo, api_key)

        enriched[full_name] = {
            'hash': repo_hash,
            'inferred_topics': inferred,
            'enriched_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }

        if (i + 1) % 10 == 0:
            with open(cache_path, 'w') as f:
                json.dump(enriched, f, indent=2)

        time.sleep(1.0)

    with open(cache_path, 'w') as f:
        json.dump(enriched, f, indent=2)

    return enriched


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='Path to repos JSON (flat list)')
    parser.add_argument('--cache', default='data/enriched_repos.json', help='Cache file path')
    args = parser.parse_args()

    api_key = os.environ.get('NVIDIA_API_KEY')
    if not api_key:
        print("Error: NVIDIA_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    with open(args.input) as f:
        repos = json.load(f)

    print(f"Loaded {len(repos)} repos")
    enriched = enrich_repos(repos, api_key, Path(args.cache))
    print(f"Enriched {len(enriched)} repos")

    total_inferred = sum(len(v.get('inferred_topics', [])) for v in enriched.values())
    print(f"Total inferred topics: {total_inferred}")
    if enriched:
        print(f"Avg topics per repo: {total_inferred/len(enriched):.1f}")
