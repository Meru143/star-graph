#!/usr/bin/env python3
"""
Recommendation engine: "I use X and Y, what else fits my stack?"
Uses graph neighbors + embedding similarity.
Detects stale embeddings and warns.
"""
import json, sys, argparse, os
from pathlib import Path
import numpy as np

GRAPH_FILE = Path(__file__).parent.parent / 'data' / 'star_graph_enhanced.json'
EMBEDDINGS_FILE = Path(__file__).parent.parent / 'data' / 'repo_embeddings.npy'
EMBEDDINGS_META_FILE = Path(__file__).parent.parent / 'data' / 'repo_embeddings_meta.json'


def load_graph():
    with open(GRAPH_FILE) as f:
        return json.load(f)


def get_repo_profile(graph, repo_name):
    for node in graph['nodes']:
        if node['key'] == repo_name and node['attributes'].get('type') == 'repo':
            attrs = node['attributes']
            return {
                'tech_stack': set(attrs.get('tech_stack', [])),
                'inferred_topics': set(attrs.get('inferred_topics', [])),
                'explicit_topics': set(t for t in attrs.get('all_topics', '').split('|') if t),
                'use_cases': set(attrs.get('use_cases', [])),
                'architecture': set(attrs.get('architecture_patterns', [])),
                'language': attrs.get('language', ''),
            }
    return None


def graph_based_recommendations(graph, seed_repos, top_k=10):
    seed_profiles = {}
    for repo in seed_repos:
        profile = get_repo_profile(graph, repo)
        if profile:
            seed_profiles[repo] = profile

    if not seed_profiles:
        return []

    seed_tech = set()
    seed_topics = set()
    seed_use_cases = set()
    seed_arch = set()
    for p in seed_profiles.values():
        seed_tech.update(p['tech_stack'])
        seed_topics.update(p['inferred_topics'])
        seed_topics.update(p['explicit_topics'])
        seed_use_cases.update(p['use_cases'])
        seed_arch.update(p['architecture'])

    scores = {}
    for node in graph['nodes']:
        if node['attributes'].get('type') != 'repo':
            continue
        repo = node['key']
        if repo in seed_repos:
            continue

        attrs = node['attributes']
        score = 0

        repo_tech = set(attrs.get('tech_stack', []))
        score += len(seed_tech & repo_tech) * 3

        repo_topics = set(attrs.get('inferred_topics', [])) | set(t for t in attrs.get('all_topics', '').split('|') if t)
        score += len(seed_topics & repo_topics) * 2

        repo_use = set(attrs.get('use_cases', []))
        score += len(seed_use_cases & repo_use) * 2

        repo_arch = set(attrs.get('architecture_patterns', []))
        score += len(seed_arch & repo_arch) * 1

        if score > 0:
            scores[repo] = score

    return sorted(scores.items(), key=lambda x: -x[1])[:top_k]


def build_embeddings(graph):
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
    with open(EMBEDDINGS_META_FILE, 'w') as f:
        json.dump({'repos': repos}, f)

    return embeddings, repos


def load_embeddings():
    if EMBEDDINGS_FILE.exists() and EMBEDDINGS_META_FILE.exists():
        embeddings = np.load(EMBEDDINGS_FILE)
        with open(EMBEDDINGS_META_FILE) as f:
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
        recs = graph_based_recommendations(graph, seed_repos, args.top_k)
        for repo, score in recs:
            for node in graph['nodes']:
                if node['key'] == repo:
                    attrs = node['attributes']
                    print(f"  {repo} (score: {score}) - {attrs.get('language', '')} - {attrs.get('primary_purpose', attrs.get('description', '')[:60])}")
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
