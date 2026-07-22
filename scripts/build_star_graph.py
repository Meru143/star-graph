#!/usr/bin/env python3
"""
Build bipartite star graph: Repos <-> Topics (explicit + inferred).
Incremental: diffs against last_starred_state.json, enriches only new/changed.
Outputs: star_graph.json (Graphology), star_graph.graphml (Gephi/Cytoscape)
"""
import json, hashlib, sys, time, os
from pathlib import Path
import networkx as nx

sys.path.insert(0, str(Path(__file__).parent))
from graph_utils import normalize_topic

DATA_DIR = Path(__file__).parent.parent / 'data'
STATE_FILE = DATA_DIR / 'last_starred_state.json'
ENRICHED_FILE = DATA_DIR / 'enriched_repos.json'
RAW_FILE = DATA_DIR / 'starred_raw.json'
GRAPH_JSON = DATA_DIR / 'star_graph.json'
GRAPH_GRAPHML = DATA_DIR / 'star_graph.graphml'
MERMAID_FILE = DATA_DIR / 'star_graph.mermaid'


def compute_repo_hash(repo):
    mutable = f"{repo.get('description','')}|{json.dumps(repo.get('topics',[]), sort_keys=True)}|{repo.get('language','')}"
    return hashlib.sha256(mutable.encode()).hexdigest()[:16]


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'repos': {}}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def load_enriched():
    if ENRICHED_FILE.exists():
        with open(ENRICHED_FILE) as f:
            return json.load(f)
    return {}


def load_raw_repos():
    with open(RAW_FILE) as f:
        data = json.load(f)
    # Handle --slurp output: array of page arrays -> flatten
    if data and isinstance(data[0], list):
        data = [repo for page in data for repo in page]
    return data


def build_graph(repos, enriched):
    G = nx.Graph()

    for repo in repos:
        full_name = repo['full_name']
        repo_hash = compute_repo_hash(repo)

        explicit = [normalize_topic(t) for t in repo.get('topics', []) if normalize_topic(t)]
        inferred = [normalize_topic(t) for t in enriched.get(full_name, {}).get('inferred_topics', []) if normalize_topic(t)]
        all_topics = list(dict.fromkeys(explicit + inferred))  # dedupe preserving order

        G.add_node(full_name,
                   type='repo',
                   description=repo.get('description', '') or '',
                   language=repo.get('language', '') or '',
                   stargazers_count=repo.get('stargazers_count', 0),
                   html_url=repo.get('html_url', '') or '',
                   hash=repo_hash,
                   explicit_topics='|'.join(explicit),
                   inferred_topics='|'.join(inferred),
                   all_topics='|'.join(all_topics),
                   enriched_at=enriched.get(full_name, {}).get('enriched_at', '') or '')

        for topic in all_topics:
            if not G.has_node(topic):
                G.add_node(topic, type='topic')
            G.add_edge(full_name, topic)

    return G


def export_graph(G):
    # Graphology JSON
    graphology = {'nodes': [], 'edges': []}
    for node, data in G.nodes(data=True):
        graphology['nodes'].append({'key': node, 'attributes': data})
    for u, v, data in G.edges(data=True):
        graphology['edges'].append({'source': u, 'target': v, 'attributes': data})

    with open(GRAPH_JSON, 'w') as f:
        json.dump(graphology, f, indent=2)
    print(f"Written {GRAPH_JSON} ({len(G.nodes())} nodes, {len(G.edges())} edges)")

    # GraphML
    G_copy = nx.Graph()
    for node, data in G.nodes(data=True):
        gml_data = {}
        for k, v in data.items():
            if v is None:
                gml_data[k] = ''
            elif isinstance(v, (list, dict)):
                gml_data[k] = json.dumps(v)
            else:
                gml_data[k] = str(v)
        G_copy.add_node(node, **gml_data)
    for u, v, data in G.edges(data=True):
        gml_edge = {}
        for k, v in data.items():
            gml_edge[k] = str(v) if v is not None else ''
        G_copy.add_edge(u, v, **gml_edge)

    nx.write_graphml(G_copy, GRAPH_GRAPHML)
    print(f"Written {GRAPH_GRAPHML}")

    # Mermaid
    repo_nodes = [n for n, d in G.nodes(data=True) if d.get('type') == 'repo']
    topic_nodes = [n for n, d in G.nodes(data=True) if d.get('type') == 'topic']

    topic_degrees = [(t, G.degree(t)) for t in topic_nodes]
    topic_degrees.sort(key=lambda x: -x[1])
    top_topics = set(t for t, _ in topic_degrees[:30])

    connected_repos = set()
    for topic in top_topics:
        connected_repos.update(G.neighbors(topic))

    mermaid_lines = ['graph TD']
    for repo in connected_repos:
        if G.nodes[repo].get('type') != 'repo':
            continue
        for topic in G.neighbors(repo):
            if topic in top_topics:
                mermaid_lines.append(f'  {repo.replace("/", "_").replace("-", "_")}["{repo}"] --> {topic.replace("-", "_")}["{topic}"]')
    for topic in top_topics:
        mermaid_lines.append(f'  {topic.replace("-", "_")}["{topic}"]:::topic')
    mermaid_lines.append('  classDef topic fill:#f9f,stroke:#333,stroke-width:2px;')

    with open(MERMAID_FILE, 'w') as f:
        f.write('\n'.join(mermaid_lines))
    print(f"Written {MERMAID_FILE}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Skip API calls, use cache only')
    args = parser.parse_args()

    print("Loading raw repos...")
    repos = load_raw_repos()
    print(f"Total starred repos: {len(repos)}")

    print("Loading state...")
    state = load_state()
    enriched = load_enriched()

    new_or_changed = []
    current_state = {}

    for repo in repos:
        full_name = repo['full_name']
        repo_hash = compute_repo_hash(repo)
        current_state[full_name] = {
            'hash': repo_hash,
            'starred_at': repo.get('starred_at', ''),
            'language': repo.get('language', '')
        }

        if full_name not in state['repos']:
            new_or_changed.append(repo)
        elif state['repos'][full_name].get('hash') != repo_hash:
            new_or_changed.append(repo)

    unstarred = set(state['repos'].keys()) - set(current_state.keys())
    if unstarred:
        print(f"Unstarred: {len(unstarred)} repos")

    print(f"New/changed repos: {len(new_or_changed)}")

    if new_or_changed and not args.dry_run:
        print("Enriching new/changed repos...")
        import subprocess
        temp_file = DATA_DIR / 'temp_new_repos.json'
        with open(temp_file, 'w') as f:
            json.dump(new_or_changed, f)

        api_key = os.environ.get('NVIDIA_API_KEY')
        if api_key:
            result = subprocess.run([
                sys.executable, str(Path(__file__).parent / 'enrich_repo.py'),
                '--input', str(temp_file),
                '--cache', str(ENRICHED_FILE),
            ], capture_output=True, text=True, timeout=300,
               env={**os.environ, 'NVIDIA_API_KEY': api_key})
            if result.returncode != 0:
                print(f"Enrichment failed: {result.stderr}", file=sys.stderr)
            else:
                print("Enrichment complete")
                enriched = load_enriched()
        else:
            print("NVIDIA_API_KEY not set, skipping enrichment")
        temp_file.unlink(missing_ok=True)

    print("Building graph...")
    G = build_graph(repos, enriched)

    print("Exporting...")
    export_graph(G)

    state['repos'] = current_state
    state['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    state['total_repos'] = len(repos)
    state['total_nodes'] = len(G.nodes())
    state['total_edges'] = len(G.edges())
    save_state(state)
    print("State saved.")

    repo_count = sum(1 for _, d in G.nodes(data=True) if d.get('type') == 'repo')
    topic_count = sum(1 for _, d in G.nodes(data=True) if d.get('type') == 'topic')
    print(f"\nGraph Summary:")
    print(f"  Repos: {repo_count}")
    print(f"  Topics: {topic_count}")
    print(f"  Edges: {G.number_of_edges()}")


if __name__ == '__main__':
    main()
