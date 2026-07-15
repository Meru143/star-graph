#!/usr/bin/env python3
"""
Query utilities for star graph.
"""
import json, sys
from pathlib import Path

GRAPH_FILE = Path(__file__).parent.parent / 'data' / 'star_graph.json'

def load_graph():
    with open(GRAPH_FILE) as f:
        return json.load(f)

def find_by_topic(graph, topic):
    """Find repos connected to a topic."""
    topic_lower = topic.lower()
    results = []
    topic_node = None
    for n in graph['nodes']:
        if n['attributes'].get('type') == 'topic' and n['key'].lower() == topic_lower:
            topic_node = n
            break
    if not topic_node:
        return []
    
    # Find connected repos
    connected_repos = set()
    for e in graph['edges']:
        if e['source'] == topic_node['key']:
            connected_repos.add(e['target'])
        elif e['target'] == topic_node['key']:
            connected_repos.add(e['source'])
    
    for n in graph['nodes']:
        if n['key'] in connected_repos and n['attributes'].get('type') == 'repo':
            results.append(n)
    return results

def find_by_language_and_topic(graph, language, topic):
    """Find repos by language and topic."""
    repos = find_by_topic(graph, topic)
    lang_lower = language.lower()
    return [r for r in repos if r['attributes'].get('language', '').lower() == lang_lower]

def topic_cooccurrence(graph, topic):
    """Find topics that co-occur with given topic."""
    topic_lower = topic.lower()
    topic_node = None
    for n in graph['nodes']:
        if n['attributes'].get('type') == 'topic' and n['key'].lower() == topic_lower:
            topic_node = n
            break
    if not topic_node:
        return []
    
    # Find repos with this topic
    repo_ids = set()
    for e in graph['edges']:
        if e['source'] == topic_node['key']:
            repo_ids.add(e['target'])
        elif e['target'] == topic_node['key']:
            repo_ids.add(e['source'])
    
    # Find other topics in those repos
    cooccur = {}
    for e in graph['edges']:
        if e['source'] in repo_ids and e['target'] != topic_node['key']:
            t = e['target']
        elif e['target'] in repo_ids and e['source'] != topic_node['key']:
            t = e['source']
        else:
            continue
        # Verify it's a topic
        for n in graph['nodes']:
            if n['key'] == t and n['attributes'].get('type') == 'topic':
                cooccur[t] = cooccur.get(t, 0) + 1
                break
    
    return sorted(cooccur.items(), key=lambda x: -x[1])

def recommend_similar(graph, repo_name):
    """Find repos similar to given repo based on shared topics."""
    repo_node = None
    for n in graph['nodes']:
        if n['key'] == repo_name and n['attributes'].get('type') == 'repo':
            repo_node = n
            break
    if not repo_node:
        return []
    
    # Get repo's topics
    repo_topics = set()
    for e in graph['edges']:
        if e['source'] == repo_name:
            repo_topics.add(e['target'])
        elif e['target'] == repo_name:
            repo_topics.add(e['source'])
    
    # Score other repos by shared topics
    scores = {}
    for n in graph['nodes']:
        if n['key'] == repo_name or n['attributes'].get('type') != 'repo':
            continue
        shared = 0
        for e in graph['edges']:
            if e['source'] == n['key'] and e['target'] in repo_topics:
                shared += 1
            elif e['target'] == n['key'] and e['source'] in repo_topics:
                shared += 1
        if shared > 0:
            scores[n['key']] = shared
    
    return sorted(scores.items(), key=lambda x: -x[1])[:10]

def export_mermaid(graph, output_path, topic_filter=None):
    """Export subgraph as Mermaid diagram."""
    repo_nodes = [n for n in graph['nodes'] if n['attributes'].get('type') == 'repo']
    topic_nodes = [n for n in graph['nodes'] if n['attributes'].get('type') == 'topic']
    
    if topic_filter:
        topic_nodes = [t for t in topic_nodes if topic_filter.lower() in t['key'].lower()]
    
    topic_degrees = [(t, sum(1 for e in graph['edges'] if e['source'] == t['key'] or e['target'] == t['key'])) 
                     for t in topic_nodes]
    topic_degrees.sort(key=lambda x: -x[1])
    top_topics = set(t['key'] for t, _ in topic_degrees[:20])
    
    connected_repos = set()
    for topic in top_topics:
        for e in graph['edges']:
            if e['source'] == topic:
                connected_repos.add(e['target'])
            elif e['target'] == topic:
                connected_repos.add(e['source'])
    
    lines = ['graph TD']
    for repo_id in connected_repos:
        for e in graph['edges']:
            if e['source'] == repo_id and e['target'] in top_topics:
                lines.append(f'  {repo_id.replace("/", "_").replace("-", "_")}["{repo_id}"] --> {e["target"].replace("-", "_")}["{e["target"]}"]')
            elif e['target'] == repo_id and e['source'] in top_topics:
                lines.append(f'  {repo_id.replace("/", "_").replace("-", "_")}["{repo_id}"] --> {e["source"].replace("-", "_")}["{e["source"]}"]')
    
    for topic in top_topics:
        lines.append(f'  {topic.replace("-", "_")}["{topic}"]:::topic')
    lines.append('  classDef topic fill:#f9f,stroke:#333,stroke-width:2px;')
    
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"Exported to {output_path}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--topic', help='Find repos by topic')
    parser.add_argument('--language', help='Filter by language')
    parser.add_argument('--cooccur', help='Topic co-occurrence')
    parser.add_argument('--similar', help='Find similar repos')
    parser.add_argument('--mermaid', help='Export mermaid for topic')
    parser.add_argument('--output', help='Output file for mermaid')
    args = parser.parse_args()
    
    graph = load_graph()
    
    if args.topic:
        repos = find_by_topic(graph, args.topic)
        if args.language:
            repos = [r for r in repos if r['attributes'].get('language', '').lower() == args.language.lower()]
        for r in repos:
            print(f"  {r['key']} - {r['attributes'].get('language', '')} - {r['attributes'].get('description', '')[:80]}")
    
    elif args.cooccur:
        for topic, count in topic_cooccurrence(graph, args.cooccur)[:20]:
            print(f"  {topic}: {count}")
    
    elif args.similar:
        for repo, score in recommend_similar(graph, args.similar):
            print(f"  {repo}: {score} shared topics")
    
    elif args.mermaid:
        export_mermaid(graph, Path(args.output or f'data/{args.mermaid}_subgraph.mermaid'), args.mermaid)
    
    else:
        print("Usage: --topic TOPIC [--language LANG] | --cooccur TOPIC | --similar REPO | --mermaid TOPIC [--output FILE]")

if __name__ == '__main__':
    main()
