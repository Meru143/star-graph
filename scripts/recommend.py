#!/usr/bin/env python3
"""
Recommendation engine: "I use X and Y, what else fits my stack?"
Uses graph neighbors + embedding similarity.
Detects stale embeddings and warns.
"""
import json, sys, argparse, os, math
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

GRAPH_FILE = Path(__file__).parent.parent / 'data' / 'star_graph_enhanced.json'
EMBEDDINGS_FILE = Path(__file__).parent.parent / 'data' / 'repo_embeddings.npy'
EMBEDDINGS_META_FILE = Path(__file__).parent.parent / 'data' / 'repo_embeddings_meta.json'


def load_graph():
    with open(GRAPH_FILE, encoding='utf-8') as f:
        return json.load(f)

def as_set(value):
    if isinstance(value, str):
        return {item for item in value.split('|') if item}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str) and item}
    return set()


def get_repo_profile(graph, repo_name):
    for node in graph['nodes']:
        if node['key'] == repo_name and node['attributes'].get('type') == 'repo':
            attrs = node['attributes']
            return {
                'tech_stack': as_set(attrs.get('tech_stack', [])),
                'inferred_topics': as_set(attrs.get('inferred_topics', [])),
                'explicit_topics': as_set(attrs.get('explicit_topics', attrs.get('all_topics', ''))),
                'use_cases': as_set(attrs.get('use_cases', [])),
                'architecture': as_set(attrs.get('architecture_patterns', [])),
                'language': attrs.get('language', ''),
            }
    return None


def graph_based_recommendations(graph, seed_repos, top_k=10, explain=False):
    seed_profiles = {
        repo: profile
        for repo in seed_repos
        if (profile := get_repo_profile(graph, repo))
    }
    if not seed_profiles:
        return []

    field_weights = {
        'tech_stack': 3,
        'inferred_topics': 2,
        'explicit_topics': 2,
        'use_cases': 2,
        'architecture': 1,
    }
    profiles = {
        node['key']: get_repo_profile(graph, node['key'])
        for node in graph['nodes']
        if node['attributes'].get('type') == 'repo'
    }
    document_frequency = Counter(
        (field, value)
        for profile in profiles.values()
        for field in field_weights
        for value in profile[field]
    )
    seed_values = {
        field: set().union(*(profile[field] for profile in seed_profiles.values()))
        for field in field_weights
    }

    scores = []
    repo_count = max(len(profiles), 1)
    for repo, profile in profiles.items():
        if repo in seed_repos:
            continue
        score = 0.0
        reasons = []
        for field, multiplier in field_weights.items():
            overlap = seed_values[field] & profile[field]
            if not overlap:
                continue
            score += sum(
                multiplier * (math.log((repo_count + 1) / (document_frequency[(field, value)] + 1)) + 1)
                for value in overlap
            )
            reasons.append(f"{field.replace('_', ' ')}: {', '.join(sorted(overlap)[:3])}")
        if score > 0:
            scores.append((repo, score, reasons))

    scores.sort(key=lambda item: (-item[1], item[0]))
    return [item if explain else item[:2] for item in scores[:top_k]]


def build_embeddings(graph):
    import numpy as np
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("sentence-transformers not installed. pip install sentence-transformers")
        return None

    model = SentenceTransformer('all-MiniLM-L6-v2')

    repos = []
    texts = []
    for node in graph['nodes']:
        if node['attributes'].get('type') != 'repo':
            continue
        repo = node['key']
        attrs = node['attributes']
        parts = [
            attrs.get('description', ''),
            attrs.get('primary_purpose', ''),
            ' '.join(attrs.get('tech_stack', [])),
            ' '.join(attrs.get('inferred_topics', [])),
            ' '.join(attrs.get('use_cases', [])),
            attrs.get('language', ''),
        ]
        text = ' '.join(filter(None, parts))
        repos.append(repo)
        texts.append(text)

    print(f"Encoding {len(texts)} repo descriptions...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32)

    np.save(EMBEDDINGS_FILE, embeddings)
    with open(EMBEDDINGS_META_FILE, 'w', encoding='utf-8') as f:
        json.dump({'repos': repos}, f)

    return embeddings, repos


def load_embeddings():
    import numpy as np
    if EMBEDDINGS_FILE.exists() and EMBEDDINGS_META_FILE.exists():
        embeddings = np.load(EMBEDDINGS_FILE)
        with open(EMBEDDINGS_META_FILE, encoding='utf-8') as f:
            meta = json.load(f)
        return embeddings, meta['repos']
    return None, None


def check_embedding_staleness(graph, repo_list):
    """Warn if embeddings are missing repos from the graph."""
    graph_repos = {n['key'] for n in graph['nodes'] if n['attributes'].get('type') == 'repo'}
    embedded_repos = set(repo_list)
    missing = graph_repos - embedded_repos
    if missing:
        print(f"WARNING: {len(missing)} repos not in embeddings (stale). Run --build-embeddings to update.")
    return len(missing) == 0


def embedding_recommendations(seed_repos, graph, top_k=10):
    import numpy as np
    embeddings, repos = load_embeddings()
    if embeddings is None:
        return []

    check_embedding_staleness(graph, repos)

    repo_to_idx = {r: i for i, r in enumerate(repos)}
    seed_idxs = [repo_to_idx[r] for r in seed_repos if r in repo_to_idx]
    if not seed_idxs:
        return []

    seed_emb = np.mean(embeddings[seed_idxs], axis=0)
    sims = np.dot(embeddings, seed_emb) / (np.linalg.norm(embeddings, axis=1) * np.linalg.norm(seed_emb) + 1e-8)

    scores = []
    for i, repo in enumerate(repos):
        if repo not in seed_repos:
            scores.append((repo, float(sims[i])))

    return sorted(scores, key=lambda x: -x[1])[:top_k]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repos', help='Comma-separated seed repos (optional if --build-embeddings)')
    parser.add_argument('--method', choices=['graph', 'embedding', 'both'], default='graph')
    parser.add_argument('--top-k', type=int, default=10)
    parser.add_argument('--build-embeddings', action='store_true', help='Build embeddings from scratch')
    args = parser.parse_args()

    print("Loading graph...")
    graph = load_graph()

    if args.build_embeddings:
        print("Building embeddings...")
        build_embeddings(graph)
        if not args.repos:
            print("Embeddings built. Pass --repos to get recommendations.")
            return

    if not args.repos:
        print("Error: --repos is required (unless only using --build-embeddings)")
        sys.exit(1)

    seed_repos = [r.strip() for r in args.repos.split(',')]

    if args.method in ['graph', 'both']:
        print("\n=== Graph-based Recommendations ===")
        recs = graph_based_recommendations(graph, seed_repos, args.top_k, explain=True)
        for repo, score, reasons in recs:
            for node in graph['nodes']:
                if node['key'] == repo:
                    attrs = node['attributes']
                    print(f"  {repo} (score: {score:.2f}) - {attrs.get('language', '')} - {attrs.get('primary_purpose', attrs.get('description', '')[:60])}")
                    print(f"    Why: {'; '.join(reasons)}")
                    break

    if args.method in ['embedding', 'both']:
        if not EMBEDDINGS_FILE.exists():
            print("Building embeddings...")
            build_embeddings(graph)

        print("\n=== Embedding-based Recommendations ===")
        recs = embedding_recommendations(seed_repos, graph, args.top_k)
        for repo, score in recs:
            for node in graph['nodes']:
                if node['key'] == repo:
                    attrs = node['attributes']
                    print(f"  {repo} (sim: {score:.3f}) - {attrs.get('language', '')} - {attrs.get('primary_purpose', attrs.get('description', '')[:60])}")
                    break


if __name__ == '__main__':
    main()
