#!/usr/bin/env python3
"""
Query utilities for star graph.
Uses pre-built adjacency and type indexes for O(1) lookups.
"""
import json, sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

GRAPH_FILE = Path(__file__).parent.parent / 'data' / 'star_graph_enhanced.json'


def load_graph():
    with open(GRAPH_FILE, encoding='utf-8') as f:
        return json.load(f)


def build_indexes(graph):
    """Build adjacency list and node-type index once."""
    adj = {}
    node_type = {}
    node_attrs = {}
    for n in graph['nodes']:
        key = n['key']
        node_type[key] = n['attributes'].get('type', 'unknown')
        node_attrs[key] = n['attributes']
    for e in graph['edges']:
        adj.setdefault(e['source'], set()).add(e['target'])
        adj.setdefault(e['target'], set()).add(e['source'])
    return adj, node_type, node_attrs


def find_by_topic(graph, topic, adj, node_type, node_attrs):
    topic_lower = topic.lower()
    topic_key = None
    for key, ntype in node_type.items():
        if ntype == 'topic' and key.lower() == topic_lower:
            topic_key = key
            break
    if not topic_key:
        return []

    neighbors = adj.get(topic_key, set())
    return [
        {'key': n, 'attributes': node_attrs[n]}
        for n in neighbors
        if node_type.get(n) == 'repo'
    ]


def topic_cooccurrence(graph, topic, adj, node_type):
    topic_lower = topic.lower()
    topic_key = None
    for key, ntype in node_type.items():
        if ntype == 'topic' and key.lower() == topic_lower:
            topic_key = key
            break
    if not topic_key:
        return []

    # Repos with this topic
    repo_ids = {n for n in adj.get(topic_key, set()) if node_type.get(n) == 'repo'}

    # Other topics in those repos
    cooccur = {}
    for repo in repo_ids:
        for neighbor in adj.get(repo, set()):
            if neighbor != topic_key and node_type.get(neighbor) == 'topic':
                cooccur[neighbor] = cooccur.get(neighbor, 0) + 1

    return sorted(cooccur.items(), key=lambda x: -x[1])


def recommend_similar(graph, repo_name, adj, node_type):
    if repo_name not in node_type or node_type[repo_name] != 'repo':
        return []

    repo_neighbors = adj.get(repo_name, set())

    scores = {}
    for neighbor in repo_neighbors:
        if node_type.get(neighbor) != 'topic':
            continue
        # Other repos sharing this topic
        for other in adj.get(neighbor, set()):
            if other != repo_name and node_type.get(other) == 'repo':
                scores[other] = scores.get(other, 0) + 1

    return sorted(scores.items(), key=lambda x: -x[1])[:10]


def export_mermaid(graph, output_path, topic_filter, adj, node_type):
    topic_nodes = [k for k, t in node_type.items() if t == 'topic']

    if topic_filter:
        topic_nodes = [t for t in topic_nodes if topic_filter.lower() in t.lower()]

    topic_degrees = [(t, len(adj.get(t, set()))) for t in topic_nodes]
    topic_degrees.sort(key=lambda x: -x[1])
    top_topics = set(t for t, _ in topic_degrees[:20])

    connected_repos = set()
    for topic in top_topics:
        for n in adj.get(topic, set()):
            if node_type.get(n) == 'repo':
                connected_repos.add(n)

    lines = ['graph TD']
    for repo_id in connected_repos:
        for neighbor in adj.get(repo_id, set()):
            if neighbor in top_topics:
                lines.append(f'  {repo_id.replace("/", "_").replace("-", "_")}["{repo_id}"] --> {neighbor.replace("-", "_")}["{neighbor}"]')

    for topic in top_topics:
        lines.append(f'  {topic.replace("-", "_")}["{topic}"]:::topic')
    lines.append('  classDef topic fill:#f9f,stroke:#333,stroke-width:2px;')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"Exported to {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--topic', help='Find repos by topic')
    parser.add_argument('--domain', help='Find repos using domain aliases (e.g. cms)')
    parser.add_argument('--language', help='Filter by language')
    parser.add_argument('--cooccur', help='Topic co-occurrence')
    parser.add_argument('--similar', help='Find similar repos')
    parser.add_argument('--mermaid', help='Export mermaid for topic')
    parser.add_argument('--output', help='Output file for mermaid')
    args = parser.parse_args()

    graph = load_graph()
    adj, node_type, node_attrs = build_indexes(graph)

    if args.topic:
        repos = find_by_topic(graph, args.topic, adj, node_type, node_attrs)
        if args.language:
            repos = [r for r in repos if r['attributes'].get('language', '').lower() == args.language.lower()]
        for r in repos:
            print(f"  {r['key']} - {r['attributes'].get('language', '')} - {r['attributes'].get('description', '')[:80]}")

    elif args.cooccur:
        for topic, count in topic_cooccurrence(graph, args.cooccur, adj, node_type)[:20]:
            print(f"  {topic}: {count}")

    elif args.domain:
        sys.path.insert(0, str(Path(__file__).parent))
        from research import search_repos
        for index, result in enumerate(search_repos(graph, args.domain, domain=args.domain), 1):
            attrs = result['attributes']
            print(f"  {index}. {result['repo']} - {attrs.get('language', '')} - {attrs.get('stargazers_count', 0):,} stars")
            print(f"     Why: {'; '.join(result['reasons'])}")

    elif args.similar:
        for repo, score in recommend_similar(graph, args.similar, adj, node_type):
            print(f"  {repo}: {score} shared topics")

    elif args.mermaid:
        export_mermaid(graph, Path(args.output or f'data/{args.mermaid}_subgraph.mermaid'), args.mermaid, adj, node_type)

    else:
        print("Usage: --topic TOPIC [--language LANG] | --domain DOMAIN | --cooccur TOPIC | --similar REPO | --mermaid TOPIC [--output FILE]")


if __name__ == '__main__':
    main()
