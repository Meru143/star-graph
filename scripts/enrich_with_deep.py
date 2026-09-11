#!/usr/bin/env python3
"""
Enhance graph with deep research data (from deep_research.json).
Adds: technology, use_case, architecture_pattern nodes and edges.
Uses consistent topic normalization from graph_utils.
"""
import json, sys
from pathlib import Path
import networkx as nx

sys.path.insert(0, str(Path(__file__).parent))
from graph_utils import normalize_topic, validate_deep_analysis

DATA_DIR = Path(__file__).parent.parent / 'data'
DEEP_FILE = DATA_DIR / 'deep_research.json'
GRAPH_FILE = DATA_DIR / 'star_graph.json'
ENHANCED_JSON = DATA_DIR / 'star_graph_enhanced.json'
ENHANCED_GRAPHML = DATA_DIR / 'star_graph_enhanced.graphml'


def load_deep():
    if DEEP_FILE.exists():
        with open(DEEP_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}


def load_graph():
    with open(GRAPH_FILE, encoding='utf-8') as f:
        return json.load(f)

def add_relation(graph, repo, node, source, weight):
    if graph.has_edge(repo, node):
        edge = graph.edges[repo, node]
        sources = set(str(edge.get('source', '')).split('|')) - {''}
        sources.add(source)
        edge['source'] = '|'.join(sorted(sources))
        edge['weight'] = max(int(edge.get('weight', 1)), weight)
    else:
        graph.add_edge(repo, node, weight=weight, source=source)


def build_enhanced_graph(graph_data, deep_data):
    G = nx.Graph()

    for node in graph_data['nodes']:
        attrs = dict(node['attributes'])
        attrs.setdefault('deep_researched', False)
        attrs.setdefault('deep_analysis_status', 'missing')
        attrs.setdefault('deep_analyzed_at', '')
        attrs.setdefault('deep_model', '')
        G.add_node(node['key'], **attrs)

    for edge in graph_data['edges']:
        G.add_edge(edge['source'], edge['target'], **edge.get('attributes', {}))

    for full_name, data in deep_data.items():
        if not isinstance(data, dict):
            continue
        if not G.has_node(full_name):
            continue
        raw_analysis = data.get('deep_analysis', {})
        analysis = validate_deep_analysis(raw_analysis) if raw_analysis else {}
        node = G.nodes[full_name]
        node['deep_researched'] = True
        node['deep_analysis_status'] = 'complete' if analysis else 'missing'
        node['deep_analyzed_at'] = data.get('analyzed_at', '') or ''
        node['deep_model'] = data.get('model', '') or ''
        if not analysis:
            continue

        # Add inferred topics
        for topic in analysis.get('inferred_topics', []):
            topic = normalize_topic(topic)
            if not topic:
                continue
            if not G.has_node(topic):
                G.add_node(topic, type='topic', label=topic)
            add_relation(G, full_name, topic, 'deep_inferred', 2)

        # Add technologies
        for tech in analysis.get('tech_stack', []):
            tech = normalize_topic(tech)
            if not tech:
                continue
            if not G.has_node(tech):
                G.add_node(tech, type='technology', label=tech)
            add_relation(G, full_name, tech, 'deep_tech', 2)

        # Add architecture patterns
        for pattern in analysis.get('architecture_patterns', []):
            pattern = normalize_topic(pattern)
            if not pattern:
                continue
            if not G.has_node(pattern):
                G.add_node(pattern, type='architecture', label=pattern)
            add_relation(G, full_name, pattern, 'deep_arch', 1)

        # Add use cases
        for uc in analysis.get('use_cases', []):
            uc = normalize_topic(uc)
            if not uc:
                continue
            if not G.has_node(uc):
                G.add_node(uc, type='use_case', label=uc)
            add_relation(G, full_name, uc, 'deep_use_case', 2)

        # Add maturity, audience as node attributes
        G.nodes[full_name]['maturity'] = analysis.get('maturity', '')
        G.nodes[full_name]['target_audience'] = analysis.get('target_audience', '')
        G.nodes[full_name]['unique_value'] = analysis.get('unique_value', '')
        G.nodes[full_name]['complexity_score'] = analysis.get('complexity_score', 0)
        G.nodes[full_name]['production_ready'] = analysis.get('production_ready', False)
        G.nodes[full_name]['primary_purpose'] = analysis.get('primary_purpose', '')
        G.nodes[full_name]['tech_stack'] = analysis.get('tech_stack', [])
        G.nodes[full_name]['use_cases'] = analysis.get('use_cases', [])
        G.nodes[full_name]['architecture_patterns'] = analysis.get('architecture_patterns', [])
        base_topics = G.nodes[full_name].get('inferred_topics', [])
        if isinstance(base_topics, str):
            base_topics = [topic for topic in base_topics.split('|') if topic]
        G.nodes[full_name]['inferred_topics'] = list(dict.fromkeys(
            list(base_topics) + analysis.get('inferred_topics', [])
        ))
        G.nodes[full_name]['deep_inferred_topics'] = analysis.get('inferred_topics', [])

    return G


def export_enhanced(G):
    graphology = {'nodes': [], 'edges': []}
    for node, attrs in G.nodes(data=True):
        graphology['nodes'].append({'key': node, 'attributes': attrs})
    for u, v, attrs in G.edges(data=True):
        graphology['edges'].append({'source': u, 'target': v, 'attributes': attrs})

    with open(ENHANCED_JSON, 'w', encoding='utf-8') as f:
        json.dump(graphology, f, indent=2)
    print(f"Enhanced JSON: {ENHANCED_JSON} ({len(G.nodes())} nodes, {len(G.edges())} edges)")

    # GraphML
    G_copy = nx.Graph()
    for node, attrs in G.nodes(data=True):
        gml_attrs = {}
        for k, v in attrs.items():
            if v is None:
                gml_attrs[k] = ''
            elif isinstance(v, (list, dict)):
                gml_attrs[k] = json.dumps(v)
            else:
                gml_attrs[k] = str(v)
        G_copy.add_node(node, **gml_attrs)
    for u, v, attrs in G.edges(data=True):
        gml_attrs = {k: str(v) if v is not None else '' for k, v in attrs.items()}
        G_copy.add_edge(u, v, **gml_attrs)

    nx.write_graphml(G_copy, ENHANCED_GRAPHML)
    print(f"Enhanced GraphML: {ENHANCED_GRAPHML}")


def export_domain_mermaids(G):
    domains = {
        'ai_agents': ['ai-agents', 'agent-framework', 'multi-agent', 'langchain', 'autogen', 'crewai', 'agent-skills'],
        'llm_inference': ['llm-inference', 'vllm', 'tensorrt-llm', 'sglang', 'text-generation-inference', 'model-serving'],
        'trading': ['algorithmic-trading', 'quantitative-finance', 'backtesting', 'portfolio-optimization', 'risk-management'],
        'devtools': ['developer-tools', 'cli-tools', 'code-generation', 'debugging', 'profiling', 'testing-tools'],
        'security': ['security-scanning', 'vulnerability-scanning', 'secrets-management', 'compliance', 'sast'],
        'video_content': ['video-editing', 'video-generation', 'content-creation', 'youtube-automation', 'tiktok'],
        'data_engineering': ['data-pipeline', 'etl', 'data-quality', 'data-catalog', 'lakehouse', 'delta-lake'],
        'web_scraping': ['web-scraping', 'crawler', 'browser-automation', 'playwright', 'puppeteer'],
    }

    for domain_name, seed_topics in domains.items():
        related = set()
        for seed in seed_topics:
            if G.has_node(seed):
                related.add(seed)
                related.update(G.neighbors(seed))

        sub_nodes = [n for n in related if G.nodes[n].get('type') in ['repo', 'topic', 'technology', 'use_case', 'architecture']]
        if len(sub_nodes) < 5:
            continue

        lines = [f'graph TD', f'  subgraph {domain_name} ["{domain_name.replace("_", " ").title()}"]']
        for node in sub_nodes:
            ntype = G.nodes[node].get('type', '')
            clean = node.replace("/", "_").replace("-", "_").replace(".", "_")
            if ntype == 'repo':
                lines.append(f'    {clean}["{node}"]:::repo')
            elif ntype in ['topic', 'technology', 'use_case', 'architecture']:
                lines.append(f'    {clean}["{node}"]:::{ntype}')
        lines.append('  end')

        sub_set = set(sub_nodes)
        for u, v in G.edges():
            if u in sub_set and v in sub_set:
                u_clean = u.replace("/", "_").replace("-", "_").replace(".", "_")
                v_clean = v.replace("/", "_").replace("-", "_").replace(".", "_")
                lines.append(f'  {u_clean} --> {v_clean}')

        lines.extend([
            '  classDef repo fill:#1f6feb,color:#fff;',
            '  classDef topic fill:#a371f7,color:#fff;',
            '  classDef technology fill:#3fb950,color:#fff;',
            '  classDef use_case fill:#d29922,color:#fff;',
            '  classDef architecture fill:#f85149,color:#fff;'
        ])

        with open(DATA_DIR / f'star_graph_{domain_name}.mermaid', 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"  Domain Mermaid: {domain_name} ({len(sub_nodes)} nodes)")


if __name__ == '__main__':
    print("Loading data...")
    deep = load_deep()
    graph_data = load_graph()

    print(f"Deep research: {len(deep)} repos")
    print(f"Graph: {len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges")

    print("Building enhanced graph...")
    G = build_enhanced_graph(graph_data, deep)

    print("Exporting...")
    export_enhanced(G)
    export_domain_mermaids(G)

    types = {}
    for _, attrs in G.nodes(data=True):
        t = attrs.get('type', 'unknown')
        types[t] = types.get(t, 0) + 1
    print(f"\nNode types: {types}")
    print("Done!")
