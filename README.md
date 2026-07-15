# Star Graph 🌟

Interactive knowledge graph of your GitHub starred repositories with **LLM-inferred latent topics**.

## What is this?

You star 363 repos. GitHub gives you ~1,765 explicit topics. But 84 repos (23%) have **zero topics** — invisible to topic-based discovery.

This graph fixes that by using **Llama-3.1-70B-Instruct (NVIDIA NIM)** to infer latent topics from descriptions. Now every repo has 5-8 meaningful tags.

## Graph Structure

- **Nodes**: 363 repos + 1,845 topics
- **Edges**: 3,420 (repo ↔ topic connections)
- **Bipartite**: Repos connect to topics; topics connect to co-occurring topics
- **Explicit topics**: From GitHub API (your stars' actual tags)
- **Inferred topics**: LLM-generated latent use-cases (youtube-content-creation, algorithmic-trading, ai-agents, etc.)

## View the Graph

- **Interactive (GitHub Pages)**: https://merup.me/star-graph/
- **Obsidian Mermaid**: Open `data/star_graph.mermaid` in Obsidian
- **Gephi/Cytoscape**: Import `data/star_graph.graphml`
- **Programmatic**: Load `data/star_graph.json` (Graphology format)

## Query Examples

```bash
# Find repos by topic
python scripts/query_graph.py --topic ai-agents

# Find repos by topic + language
python scripts/query_graph.py --topic ai-agents --language python

# Topic co-occurrence (what appears with "ai-agents")
python scripts/query_graph.py --cooccur ai-agents

# Recommend similar repos
python scripts/query_graph.py --similar KnockOutEZ/wigolo

# Export Mermaid subgraph for a topic
python scripts/query_graph.py --mermaid ai-agents --output data/ai-agents.mermaid
```

## Architecture

```
GitHub API (starred repos)
    ↓
LLM Enrichment (NVIDIA NIM → Llama-3.1-70B)
    ↓
Incremental Graph Builder (NetworkX)
    ↓
Graphology JSON + GraphML + Mermaid
    ↓
GitHub Pages (Sigma.js viewer) + GitHub Actions (weekly update)
```

## Weekly Auto-Update

GitHub Action runs every Monday 06:00 UTC:
1. Fetches current starred repos
2. Diffs against `last_starred_state.json`
3. Enriches only **new/changed** repos (5-10 API calls/week)
4. Rebuilds graph
5. Commits if changed

## Data Files

| File | Format | Use Case |
|------|--------|----------|
| `data/star_graph.json` | Graphology | Sigma.js, programmatic queries |
| `data/star_graph.graphml` | GraphML | Gephi, Cytoscape, yEd |
| `data/star_graph.mermaid` | Mermaid | Obsidian, GitHub, Notion |
| `data/enriched_repos.json` | JSON | LLM cache (hash-based) |
| `data/last_starred_state.json` | JSON | Incremental diff state |

## Setup for Your Own Stars

```bash
# Fork this repo
# Add NVIDIA_API_KEY secret to GitHub Actions
# Update workflow to use your GitHub user
# Enable GitHub Pages
```

## License

MIT — Graph data is your public stars; code is yours to use.
