#!/usr/bin/env python3
"""
Sync star graph to Obsidian vault.
Creates markdown notes for repos, topics, technologies, use cases with backlinks.
Uses adjacency lists for O(1) neighbor lookups.
"""
import json, re
from pathlib import Path

GRAPH_FILE = Path(__file__).parent.parent / 'data' / 'star_graph_enhanced.json'
DEEP_FILE = Path(__file__).parent.parent / 'data' / 'deep_research.json'
VAULT_DIR = Path('/root/obsidian/star-graph')


def sanitize(s):
    return re.sub(r'[^\w\-]', '-', s).strip('-')


def load_graph():
    with open(GRAPH_FILE) as f:
        g = json.load(f)
    g['nodes_dict'] = {n['key']: n['attributes'] for n in g['nodes']}
    # Build adjacency list once
    adj = {}
    for e in g['edges']:
        adj.setdefault(e['source'], []).append(e['target'])
        adj.setdefault(e['target'], []).append(e['source'])
    g['adjacency'] = adj
    return g


def load_deep():
    if DEEP_FILE.exists():
        with open(DEEP_FILE) as f:
            return json.load(f)
    return {}


def create_repo_notes(graph, deep_data):
    (VAULT_DIR / 'Repos').mkdir(parents=True, exist_ok=True)
    adj = graph['adjacency']
    nodes_dict = graph['nodes_dict']

    for node in graph['nodes']:
        if node['attributes'].get('type') != 'repo':
            continue
        key = node['key']
        attrs = node['attributes']
        deep = deep_data.get(key, {}).get('deep_analysis', {})

        # Connected repos via adjacency
        neighbors = adj.get(key, [])
        connected_repos = [n for n in neighbors if nodes_dict.get(n, {}).get('type') == 'repo'][:10]

        fm = {
            'title': key,
            'type': 'repo',
            'language': attrs.get('language', ''),
            'stars': attrs.get('stargazers_count', 0),
            'maturity': deep.get('maturity', attrs.get('maturity', '')),
            'production_ready': deep.get('production_ready', attrs.get('production_ready', False)),
            'complexity': deep.get('complexity_score', attrs.get('complexity_score', 0)),
            'tags': ['starred', 'graph'] + deep.get('inferred_topics', [])[:5]
        }

        tech_items = [f'- {t}' for t in deep.get('tech_stack', attrs.get('tech_stack', []))] or ['- N/A']
        use_items = [f'- {u}' for u in deep.get('use_cases', attrs.get('use_cases', []))] or ['- N/A']
        arch_items = [f'- {a}' for a in deep.get('architecture_patterns', attrs.get('architecture_patterns', []))] or ['- N/A']
        topic_items = [f'- [[Topics/{sanitize(t)}]]' for t in deep.get('inferred_topics', attrs.get('inferred_topics', []))] or ['- N/A']
        explicit_items = [f'- [[Topics/{sanitize(t)}]]' for t in attrs.get('all_topics', '').split('|') if t] or ['- N/A']
        connected_items = [f'- [[Repos/{sanitize(r)}]]' for r in connected_repos] or ['- N/A']

        lines = [
            '---',
            *[f'{k}: {json.dumps(v) if isinstance(v, list) else v}' for k, v in fm.items()],
            '---',
            f'# {key}',
            '',
            f'**Description:** {attrs.get("description", "No description")}',
            '',
            f'**Primary Purpose:** {deep.get("primary_purpose", attrs.get("primary_purpose", "N/A"))}',
            '',
            '## Tech Stack',
            *tech_items,
            '',
            '## Use Cases',
            *use_items,
            '',
            '## Architecture Patterns',
            *arch_items,
            '',
            '## Inferred Topics',
            *topic_items,
            '',
            '## Explicit Topics',
            *explicit_items,
            '',
            '## Connected Repos',
            *connected_items,
            '',
            f'[View on GitHub]({attrs.get("html_url", attrs.get("url", ""))})'
        ]

        filename = VAULT_DIR / 'Repos' / f'{sanitize(key)}.md'
        filename.write_text('\n'.join(lines))


def create_topic_notes(graph):
    (VAULT_DIR / 'Topics').mkdir(parents=True, exist_ok=True)
    (VAULT_DIR / 'Technologies').mkdir(parents=True, exist_ok=True)
    (VAULT_DIR / 'UseCases').mkdir(parents=True, exist_ok=True)
    (VAULT_DIR / 'Architectures').mkdir(parents=True, exist_ok=True)

    type_dirs = {
        'topic': 'Topics',
        'technology': 'Technologies',
        'use_case': 'UseCases',
        'architecture': 'Architectures'
    }

    adj = graph['adjacency']
    nodes_dict = graph['nodes_dict']

    for node in graph['nodes']:
        attrs = node['attributes']
        ntype = attrs.get('type', '')
        if ntype not in type_dirs:
            continue

        key = node['key']
        neighbors = adj.get(key, [])
        connected = [n for n in neighbors if nodes_dict.get(n, {}).get('type') == 'repo']

        lines = [
            '---',
            f'name: {key}',
            f'type: {ntype}',
            f'connected_repos: {len(connected)}',
            'tags: [starred, graph]',
            '---',
            f'# {key}',
            '',
            f'**Type:** {ntype}',
            f'**Connected Repos:** {len(connected)}',
            '',
            '## Connected Repos',
            *([f'- [[Repos/{sanitize(r)}]]' for r in sorted(connected)[:30]] or ['- None']),
        ]

        filename = VAULT_DIR / type_dirs[ntype] / f'{sanitize(key)}.md'
        filename.write_text('\n'.join(lines))


def create_index(graph):
    adj = graph['adjacency']
    nodes_dict = graph['nodes_dict']

    repos = [n for n in graph['nodes'] if n['attributes'].get('type') == 'repo']

    # Count by type
    type_counts = {}
    for n in graph['nodes']:
        t = n['attributes'].get('type', 'unknown')
        type_counts[t] = type_counts.get(t, 0) + 1

    langs = {}
    for r in repos:
        lang = r['attributes'].get('language', 'Unknown')
        langs[lang] = langs.get(lang, 0) + 1

    # Degree per node via adjacency
    degree = {k: len(v) for k, v in adj.items()}

    # Top topics (type=topic only)
    topic_degrees = [(n['key'], degree.get(n['key'], 0))
                     for n in graph['nodes'] if n['attributes'].get('type') == 'topic']
    topic_degrees.sort(key=lambda x: -x[1])

    # Top technologies (type=technology only)
    tech_degrees = [(n['key'], degree.get(n['key'], 0))
                    for n in graph['nodes'] if n['attributes'].get('type') == 'technology']
    tech_degrees.sort(key=lambda x: -x[1])

    lines = [
        '---',
        'title: Star Graph Index',
        'tags: [star-graph, index]',
        '---',
        '# Star Graph Index',
        '',
        f'**Total Repos:** {len(repos)}',
        f'**Node Types:** {json.dumps(type_counts)}',
        f'**Total Edges:** {len(graph["edges"])}',
        '',
        '## Repos by Language',
    ]

    for lang, count in sorted(langs.items(), key=lambda x: -x[1]):
        lines.append(f'- **{lang}:** {count} repos')

    lines.extend(['', '## Top Topics by Connections'])
    for topic, count in topic_degrees[:50]:
        lines.append(f'- [[Topics/{sanitize(topic)}]] ({count} repos)')

    lines.extend(['', '## Top Technologies'])
    for tech, count in tech_degrees[:50]:
        lines.append(f'- [[Technologies/{sanitize(tech)}]] ({count} repos)')

    (VAULT_DIR / 'INDEX.md').write_text('\n'.join(lines))


def main():
    print("Loading graph...")
    graph = load_graph()

    print("Loading deep research...")
    deep_data = load_deep()

    print(f"Vault: {VAULT_DIR}")
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    print("Creating repo notes...")
    create_repo_notes(graph, deep_data)

    print("Creating topic notes...")
    create_topic_notes(graph)

    print("Creating index...")
    create_index(graph)

    print("Done!")


if __name__ == '__main__':
    main()
