"""Validate generated graph, enrichment cache, and optional deep-research data."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / 'data'
sys.path.insert(0, str(Path(__file__).parent))
from graph_utils import validate_deep_analysis


def load(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def raw_repos():
    raw = load(DATA / 'starred_raw.json')
    if raw and isinstance(raw[0], list):
        raw = [repo for page in raw for repo in page]
    return raw


def repo_hash(repo):
    mutable = f"{repo.get('description', '')}|{json.dumps(repo.get('topics', []), sort_keys=True)}|{repo.get('language', '')}"
    return hashlib.sha256(mutable.encode()).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph', default=str(DATA / 'star_graph_enhanced.json'))
    parser.add_argument(
        '--allow-stale-enrichment',
        action='store_true',
        help='Report stale enrichment hashes as warnings instead of errors',
    )
    args = parser.parse_args()

    errors = []
    warnings = []
    repos = raw_repos()
    repo_names = [repo.get('full_name') for repo in repos]
    expected = set(repo_names)
    if len(repo_names) != len(expected):
        errors.append('starred_raw.json contains duplicate full_name values')

    graph = load(Path(args.graph))
    nodes = graph.get('nodes', [])
    edges = graph.get('edges', [])
    node_ids = [node.get('key') for node in nodes]
    node_set = set(node_ids)
    if len(node_ids) != len(node_set):
        errors.append('graph contains duplicate node keys')

    graph_repos = {
        node['key'] for node in nodes
        if node.get('attributes', {}).get('type') == 'repo'
    }
    if graph_repos != expected:
        errors.append(
            f'graph repo set differs from raw data (missing={len(expected - graph_repos)}, '
            f'extra={len(graph_repos - expected)})'
        )

    seen_edges = set()
    for edge in edges:
        source, target = edge.get('source'), edge.get('target')
        if source not in node_set or target not in node_set:
            errors.append(f'edge references missing node: {source} -> {target}')
        if source == target:
            errors.append(f'self-loop found: {source}')
        pair = tuple(sorted((str(source), str(target))))
        if pair in seen_edges:
            errors.append(f'duplicate edge found: {source} -> {target}')
        seen_edges.add(pair)

    for node in nodes:
        attrs = node.get('attributes', {})
        if attrs.get('type') != 'repo':
            continue
        for field in ('inferred_topics', 'tech_stack', 'use_cases', 'architecture_patterns'):
            if field in attrs and not isinstance(attrs[field], list):
                errors.append(f'{node["key"]}.{field} must be a list')
        if attrs.get('enrichment_status', 'missing') not in ('missing', 'complete', 'legacy'):
            errors.append(f'{node["key"]}.enrichment_status is invalid')

    enriched_path = DATA / 'enriched_repos.json'
    enriched = load(enriched_path) if enriched_path.exists() else {}
    if not isinstance(enriched, dict):
        errors.append('enriched_repos.json must contain an object')
        enriched = {}
    missing_cache = expected - set(enriched)
    stale_cache = set(enriched) - expected
    if missing_cache:
        warnings.append(f'{len(missing_cache)} repos have no enrichment cache entry')
    if stale_cache:
        warnings.append(f'{len(stale_cache)} retained enrichment entries are not currently starred')
    for name, entry in enriched.items():
        if not isinstance(entry, dict) or not isinstance(entry.get('inferred_topics', []), list):
            errors.append(f'{name} has invalid enrichment cache data')
    for repo in repos:
        entry = enriched.get(repo.get('full_name'))
        if entry and entry.get('hash') != repo_hash(repo):
            message = f'{repo.get("full_name")} has a stale enrichment hash'
            (warnings if args.allow_stale_enrichment else errors).append(message)

    deep_path = DATA / 'deep_research.json'
    deep = load(deep_path) if deep_path.exists() else {}
    if not isinstance(deep, dict):
        errors.append('deep_research.json must contain an object')
        deep = {}
    missing_deep = expected - set(deep)
    if missing_deep:
        warnings.append(f'{len(missing_deep)} repos have no deep-research entry')
    for name, entry in deep.items():
        if not isinstance(entry, dict):
            errors.append(f'{name} has invalid deep-research data')
        elif entry.get('deep_analysis') and not validate_deep_analysis(entry['deep_analysis']):
            warnings.append(f'{name} deep-research analysis is empty after validation')

    embeddings_meta = DATA / 'repo_embeddings_meta.json'
    if embeddings_meta.exists():
        meta_repos = set(load(embeddings_meta).get('repos', []))
        if meta_repos != graph_repos:
            warnings.append('embedding metadata does not match graph repos; rebuild embeddings')

    print(f'Validated {len(expected)} repos, {len(nodes)} nodes, {len(edges)} edges')
    print(f'Enrichment coverage: {len(expected & set(enriched))}/{len(expected)}')
    print(f'Deep-research coverage: {len(expected & set(deep))}/{len(expected)}')
    for warning in warnings:
        print(f'WARNING: {warning}')
    if errors:
        for error in errors:
            print(f'ERROR: {error}', file=sys.stderr)
        return 1
    print('OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
