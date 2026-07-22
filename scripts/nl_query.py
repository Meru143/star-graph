#!/usr/bin/env python3
"""
Natural language query over star graph using LLM + embedding-based retrieval.
Falls back to keyword matching if embeddings unavailable.
Uses NVIDIA_API_KEY env var.
"""
import json, sys, os, re
from pathlib import Path
import requests
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

GRAPH_FILE = Path(__file__).parent.parent / 'data' / 'star_graph_enhanced.json'
EMBEDDINGS_FILE = Path(__file__).parent.parent / 'data' / 'repo_embeddings.npy'
EMBEDDINGS_META_FILE = Path(__file__).parent.parent / 'data' / 'repo_embeddings_meta.json'
NVIDIA_API = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "meta/llama-3.1-70b-instruct"

QUERY_PROMPT = """You are a GitHub stars analyst. Answer the user's question using ONLY the provided graph context.

Graph Context (relevant subgraph):
{context}

Question: {question}

Rules:
- Answer directly and concisely
- Cite repo names and specific data from context
- If context doesn't contain answer, say so
- No markdown unless asked

Answer:"""


def load_graph():
    with open(GRAPH_FILE) as f:
        return json.load(f)


def load_embeddings():
    if EMBEDDINGS_FILE.exists() and EMBEDDINGS_META_FILE.exists():
        embeddings = np.load(EMBEDDINGS_FILE)
        with open(EMBEDDINGS_META_FILE) as f:
            meta = json.load(f)
        return embeddings, meta['repos']
    return None, None


def encode_query(question):
    """Encode query with same model used for repo embeddings."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        return model.encode([question])[0]
    except ImportError:
        return None


def get_relevant_subgraph_embedding(graph, question, max_nodes=80):
    """Retrieve relevant repos via embedding similarity, then expand to neighbors."""
    embeddings, repo_list = load_embeddings()
    if embeddings is None or repo_list is None:
        return None

    query_emb = encode_query(question)
    if query_emb is None:
        return None

    # Cosine similarity
    norms = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_emb) + 1e-8
    sims = np.dot(embeddings, query_emb) / norms

    # Top 20 most similar repos
    top_indices = np.argsort(-sims)[:20]
    top_repos = {repo_list[int(i)] for i in top_indices if sims[int(i)] > 0.15}

    if not top_repos:
        return None

    # Build adjacency from edges
    adjacency = {}
    for edge in graph['edges']:
        s, t = edge['source'], edge['target']
        adjacency.setdefault(s, set()).add(t)
        adjacency.setdefault(t, set()).add(s)

    # Expand 1-hop
    relevant = set(top_repos)
    for repo in top_repos:
        relevant.update(adjacency.get(repo, set()))

    sub_nodes = [n for n in graph['nodes'] if n['key'] in relevant]
    sub_edges = [e for e in graph['edges'] if e['source'] in relevant and e['target'] in relevant]

    return {'nodes': sub_nodes[:max_nodes], 'edges': sub_edges[:max_nodes * 2]}


def get_relevant_subgraph_keyword(graph, question, max_nodes=80):
    """Fallback: keyword matching with word boundaries."""
    question_lower = question.lower()
    keywords = set(re.findall(r'\b\w{3,}\b', question_lower))

    node_scores = {}
    for node in graph['nodes']:
        key = node['key'].lower()
        attrs = node['attributes']
        text = ' '.join([
            key,
            attrs.get('description', ''),
            attrs.get('primary_purpose', ''),
            attrs.get('maturity', ''),
            ' '.join(attrs.get('tech_stack', [])),
            ' '.join(attrs.get('use_cases', [])),
            ' '.join(attrs.get('inferred_topics', [])),
        ]).lower()

        score = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw) + r'\b', text))
        if score > 0:
            node_scores[node['key']] = score

    top_nodes = sorted(node_scores, key=lambda k: node_scores[k], reverse=True)[:30]
    relevant = set(top_nodes)

    for edge in graph['edges']:
        if edge['source'] in top_nodes:
            relevant.add(edge['target'])
        if edge['target'] in top_nodes:
            relevant.add(edge['source'])

    sub_nodes = [n for n in graph['nodes'] if n['key'] in relevant]
    sub_edges = [e for e in graph['edges'] if e['source'] in relevant and e['target'] in relevant]

    return {'nodes': sub_nodes[:max_nodes], 'edges': sub_edges[:max_nodes * 2]}


def get_relevant_subgraph(graph, question, max_nodes=80):
    """Try embedding retrieval first, fall back to keyword."""
    result = get_relevant_subgraph_embedding(graph, question, max_nodes)
    if result and len(result['nodes']) > 3:
        print("  (using embedding retrieval)")
        return result
    print("  (using keyword retrieval)")
    return get_relevant_subgraph_keyword(graph, question, max_nodes)


def format_context(subgraph):
    lines = []
    for node in subgraph['nodes']:
        key = node['key']
        attrs = node['attributes']
        ntype = attrs.get('type', 'unknown')
        if ntype == 'repo':
            lines.append(f"REPO: {key}")
            if attrs.get('description'):
                lines.append(f"  Desc: {attrs['description'][:200]}")
            if attrs.get('primary_purpose'):
                lines.append(f"  Purpose: {attrs['primary_purpose']}")
            if attrs.get('tech_stack'):
                lines.append(f"  Tech: {', '.join(attrs['tech_stack'][:8])}")
            if attrs.get('use_cases'):
                lines.append(f"  Use Cases: {', '.join(attrs['use_cases'][:6])}")
            if attrs.get('maturity'):
                lines.append(f"  Maturity: {attrs['maturity']}")
            if attrs.get('production_ready') is not None:
                lines.append(f"  Production Ready: {attrs['production_ready']}")
            if attrs.get('inferred_topics'):
                lines.append(f"  Topics: {', '.join(attrs['inferred_topics'][:8])}")
        elif ntype in ['topic', 'technology', 'use_case', 'architecture']:
            lines.append(f"{ntype.upper()}: {key}")

    lines.append("\nEDGES:")
    for edge in subgraph['edges'][:50]:
        lines.append(f"  {edge['source']} --({edge.get('attributes', {}).get('source', 'related')})--> {edge['target']}")

    return '\n'.join(lines)


def query_llm(question, context, api_key):
    prompt = QUERY_PROMPT.format(context=context, question=question)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "star-graph/1.0"}
    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 800, "temperature": 0.1}

    try:
        r = requests.post(NVIDIA_API, headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
        else:
            return f"LLM error: {r.status_code} - {r.text[:200]}"
    except Exception as e:
        return f"LLM error: {e}"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--question', required=True, help='Natural language question')
    parser.add_argument('--max-nodes', type=int, default=80)
    args = parser.parse_args()

    api_key = os.environ.get('NVIDIA_API_KEY')
    if not api_key:
        print("Error: NVIDIA_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    print("Loading graph...")
    graph = load_graph()

    print("Finding relevant subgraph...")
    subgraph = get_relevant_subgraph(graph, args.question, args.max_nodes)
    print(f"Subgraph: {len(subgraph['nodes'])} nodes, {len(subgraph['edges'])} edges")

    context = format_context(subgraph)

    print("Querying LLM...")
    answer = query_llm(args.question, context, api_key)

    print(f"\n--- Answer ---\n{answer}")

    repos = [n for n in subgraph['nodes'] if n['attributes'].get('type') == 'repo']
    if repos:
        print(f"\n--- Relevant Repos ({len(repos)}) ---")
        for r in sorted(repos, key=lambda x: x['attributes'].get('stargazers_count', 0), reverse=True)[:10]:
            a = r['attributes']
            print(f"  {r['key']} ({a.get('stargazers_count', 0)}*) - {a.get('primary_purpose', a.get('description', '')[:80])}")


if __name__ == '__main__':
    main()
