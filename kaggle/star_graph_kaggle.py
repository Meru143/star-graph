"""
Star-graph pipeline for Kaggle llama-server.
Calls the running llama.cpp server instead of NVIDIA NIM.

This file lives in star-graph/kaggle/ — the star-graph repo owns it.
The notebook clones BOTH repos: this file runs the pipeline,
kaggle-model-server/harness.py handles model boot.

All enrichment/deep-research prompts are identical to the original scripts.
Just the API endpoint changes from NVIDIA NIM to local llama-server.
"""

import base64, json, hashlib, os, re, subprocess, sys, time
from pathlib import Path
import requests

# --- config ----------------------------------------------------------------
LLAMA_SERVER = "http://127.0.0.1:8080"
LLAMA_URL = f"{LLAMA_SERVER}/v1/chat/completions"
STAR_GRAPH_DIR = Path("/kaggle/working/star-graph")
DATA_DIR = STAR_GRAPH_DIR / "data"
SCRIPTS_DIR = STAR_GRAPH_DIR / "scripts"


def wait_for_llama(timeout=300):
    """Wait until llama-server is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{LLAMA_SERVER}/health", timeout=5)
            if r.ok:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError("llama-server not ready within timeout")


def call_llama(prompt, system="Output ONLY valid JSON.", max_tokens=1500, temperature=0.1):
    """Call local llama-server with retries."""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature
    }
    for attempt in range(5):
        try:
            r = requests.post(LLAMA_URL, json=payload, timeout=120)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            else:
                print(f"  server error {r.status_code}: {r.text[:200]}")
                time.sleep(5 * (attempt + 1))
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"  {type(e).__name__}, retry {attempt+1}/5")
            time.sleep(10)
    return ""


def normalize_topic(s):
    if not isinstance(s, str): return ''
    s = s.lower().strip().replace(' ', '-').replace('_', '-')
    s = re.sub(r'[^a-z0-9-]', '', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s


def compute_repo_hash(repo):
    mutable = f"{repo.get('description','')}|{json.dumps(repo.get('topics',[]), sort_keys=True)}|{repo.get('language','')}"
    return hashlib.sha256(mutable.encode()).hexdigest()[:16]


# --- enrichment (mirrors enrich_repo.py) -----------------------------------

ENRICH_PROMPT = """Output ONLY a valid JSON array of 3-8 lowercase kebab-case topics for this GitHub repository.
No explanations, no markdown, no text - just the array.

Repo: {full_name}
Description: {description}
Language: {language}
Existing topics: {existing_topics}

JSON array:"""


def enrich_repos(repos, cache_path):
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    total = len(repos)
    for i, repo in enumerate(repos):
        name = repo['full_name']
        h = compute_repo_hash(repo)
        if name in cache and cache[name].get('hash') == h:
            if (i + 1) % 10 == 0: print(f"  [{i+1}/{total}] Cache hit: {name}")
            continue
        print(f"  [{i+1}/{total}] Enriching: {name}")
        content = call_llama(
            ENRICH_PROMPT.format(full_name=name, description=repo.get('description', ''),
                                 language=repo.get('language', 'Unknown'),
                                 existing_topics=repo.get('topics', [])),
            system="Output only valid JSON arrays. No text.",
            max_tokens=150, temperature=0.0)
        match = re.search(r'\[.*?\]', content, re.DOTALL)
        inferred = []
        if match:
            try:
                inferred = [normalize_topic(t) for t in json.loads(match.group()) if isinstance(t, str)][:8]
            except json.JSONDecodeError:
                print(f"  Bad JSON: {content[:100]}")
        cache[name] = {'hash': h, 'inferred_topics': inferred,
                       'enriched_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        if (i + 1) % 10 == 0:
            cache_path.write_text(json.dumps(cache, indent=2))
    cache_path.write_text(json.dumps(cache, indent=2))
    return cache


# --- deep research (mirrors deep_research.py) ------------------------------

DEEP_PROMPT = """You are a senior software architect. Analyze this GitHub repository deeply.

Repository: {full_name}
Description: {description}
Language: {language}
Stars: {stargazers_count}
Topics: {topics}

Provide a JSON object with:
{{
  "inferred_topics": ["topic1", "topic2", ...],
  "primary_purpose": "one-sentence summary",
  "tech_stack": ["tech1", ...],
  "architecture_patterns": ["pattern1", ...],
  "use_cases": ["use-case1", ...],
  "maturity": "experimental|active|stable|deprecated",
  "target_audience": "developers|data-scientists|devops|researchers|general",
  "unique_value": "what makes this different",
  "dependencies": ["dep1", ...],
  "complexity_score": 1-10,
  "production_ready": true/false
}}

Return ONLY valid JSON. No markdown."""


def deep_research_all(repos, cache_path, skip_cached=True):
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    total = len(repos)
    for i, repo in enumerate(repos):
        name = repo['full_name']
        if skip_cached and name in cache and cache[name].get('deep_analysis'):
            print(f"  [{i+1}/{total}] Cached: {name}")
            continue
        print(f"  [{i+1}/{total}] Deep: {name}")
        content = call_llama(
            DEEP_PROMPT.format(full_name=name, description=repo.get('description', ''),
                               language=repo.get('language', 'Unknown'),
                               stargazers_count=repo.get('stargazers_count', 0),
                               topics=repo.get('topics', [])),
            max_tokens=1500, temperature=0.1)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        analysis = json.loads(match.group()) if match else {}
        cache[name] = {'repo_hash': compute_repo_hash(repo), 'deep_analysis': analysis,
                       'analyzed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        if (i + 1) % 5 == 0:
            cache_path.write_text(json.dumps(cache, indent=2))
    cache_path.write_text(json.dumps(cache, indent=2))
    return cache


# --- export ----------------------------------------------------------------

def build_and_export():
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "build_star_graph.py"), "--dry-run"],
                   check=True, timeout=300, cwd=str(STAR_GRAPH_DIR))
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "enrich_with_deep.py")],
                   check=True, timeout=300, cwd=str(STAR_GRAPH_DIR))
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "recommend.py"), "--build-embeddings"],
                   check=True, timeout=600, cwd=str(STAR_GRAPH_DIR))


def git_env():
    token = os.environ.get('GH_PAT')
    if not token:
        raise RuntimeError('GH_PAT environment variable is required for git push')
    auth = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
    return {
        **os.environ,
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraheader',
        'GIT_CONFIG_VALUE_0': f'AUTHORIZATION: basic {auth}',
    }


def commit_and_push():
    result = subprocess.run(["git", "diff", "--quiet", "data/"],
                            cwd=str(STAR_GRAPH_DIR), capture_output=True)
    if result.returncode == 0:
        print("No changes")
        return
    subprocess.run(["git", "config", "user.name", "kaggle-pipeline"], cwd=str(STAR_GRAPH_DIR), check=True)
    subprocess.run(["git", "config", "user.email", "kaggle-pipeline@star-graph"], cwd=str(STAR_GRAPH_DIR), check=True)
    subprocess.run(["git", "add", "data/"], cwd=str(STAR_GRAPH_DIR), check=True)
    subprocess.run(["git", "commit", "-m", f"chore: kaggle update {time.strftime('%Y-%m-%d')}"],
                   cwd=str(STAR_GRAPH_DIR), check=True)
    subprocess.run(["git", "push", "origin", "master"],
                   cwd=str(STAR_GRAPH_DIR), check=True, env=git_env())
    print("Pushed!")


# --- main ------------------------------------------------------------------

def run_pipeline(limit=None):
    print("=" * 45 + "\nStar Graph Kaggle Pipeline\n" + "=" * 45)

    wait_for_llama()

    repos = json.loads((DATA_DIR / "starred_raw.json").read_text())
    if limit: repos = repos[:limit]
    print(f"{len(repos)} repos to process")

    print("\n[Enrich]")
    enrich_repos(repos, DATA_DIR / "enriched_repos.json")

    print("\n[Deep Research]")
    deep_research_all(repos, DATA_DIR / "deep_research.json")

    print("\n[Build + Export]")
    build_and_export()

    print("\n[Push]")
    commit_and_push()
    print("\nDone!")
