# Star Graph 🌟

Searchable knowledge graph of your GitHub starred repositories with **LLM-inferred latent topics**.

## What is this?

The current snapshot contains 622 repos and 2,456 unique GitHub topics. 169 repos (27%) have **zero explicit topics** — invisible to topic-based discovery.

This graph fills that gap with cached LLM enrichment and optional deep research. Each generated field keeps its status, model, timestamp, and source so recommendations can be inspected instead of treated as ground truth.

## Graph Structure

- **Nodes**: 622 repos + 3,742 topics + 585 technologies + 75 architecture patterns + 866 use cases (5,890 total)
- **Edges**: 11,345 in the enhanced graph (5,284 in the base graph)
- **Bipartite**: Repos connect to topics; topics connect to co-occurring topics
- **Explicit topics**: From GitHub API (your stars' actual tags)
- **Inferred topics**: LLM-generated latent use-cases (youtube-content-creation, algorithmic-trading, ai-agents, etc.)
- **Provenance**: edges identify GitHub, LLM, and deep-research sources
- **Explainability fields**: repo nodes expose enrichment/deep-research status, model, hash, and timestamps

## Use the Graph

There is no hosted website; use the local CLI or export files below.

- **Obsidian Mermaid**: Open `data/star_graph.mermaid` in Obsidian
- **Gephi/Cytoscape**: Import `data/star_graph.graphml`
- **Programmatic**: Load `data/star_graph_enhanced.json` (Graphology format)

## Query Examples

```bash
# Find repos by topic
python scripts/query_graph.py --topic ai-agents

# Find repos by topic + language
python scripts/query_graph.py --topic ai-agents --language python

# Search a project domain with aliases (CMS, headless CMS, admin platforms, etc.)
python scripts/research.py search --domain cms
python scripts/query_graph.py --domain backend-platform

# Create a Markdown research report for a new project
python scripts/research.py report --query "I'm building a Next.js content-heavy app" --output reports/nextjs-content.md

# Compare shortlisted candidates
python scripts/research.py compare --repos directus/directus,tinacms/tinacms --output reports/cms-compare.md

# Topic co-occurrence (what appears with "ai-agents")
python scripts/query_graph.py --cooccur ai-agents

# Recommend similar repos
python scripts/query_graph.py --similar KnockOutEZ/wigolo

# Explain recommendations from one or more seed repos
python scripts/recommend.py --repos KnockOutEZ/wigolo --method graph

# Validate raw data, cache coverage, and generated artifacts
python scripts/validate_data.py

# Export Mermaid subgraph for a topic
python scripts/query_graph.py --mermaid ai-agents --output data/ai-agents.mermaid
```

## Architecture

```
GitHub API (starred repos)
    ↓
Hash-based enrichment cache
    ↓
Base graph builder (NetworkX)
    ↓
Optional deep-research enrichment
    ↓
Enhanced JSON + GraphML + Mermaid + CLI queries
```

## Weekly Auto-Update

GitHub Action runs every Monday 06:00 UTC:
1. Fetches current starred repos
2. Diffs against `last_starred_state.json`
3. Reuses the hash-based enrichment and deep-research caches
4. Rebuilds graph
5. Rebuilds embeddings
6. Validates artifacts
7. Commits if changed

## Data Files

| File | Format | Use Case |
|------|--------|----------|
| `data/star_graph.json` | Graphology | Base graph and incremental builds |
| `data/star_graph_enhanced.json` | Graphology | Enriched queries and recommendations |
| `data/star_graph.graphml` | GraphML | Gephi, Cytoscape, yEd |
| `data/star_graph.mermaid` | Mermaid | Obsidian, GitHub, Notion |
| `data/enriched_repos.json` | JSON | LLM cache (hash-based) |
| `data/deep_research.json` | JSON | Optional deep-research cache |
| `data/domain_aliases.json` | JSON | Editable project-domain search aliases |
| `data/last_starred_state.json` | JSON | Incremental diff state |

## Setup for Your Own Stars

```bash
# Fork this repo
# Add provider tokens only to the relevant GitHub/Kaggle Secrets
# Update workflow to use your GitHub user
# Run the scripts locally or through GitHub Actions
```

## License

MIT — Graph data is your public stars; code is yours to use.
