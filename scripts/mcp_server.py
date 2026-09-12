"""Local MCP server for the Star Graph research knowledge base."""
import sys
from typing import Any
from pathlib import Path

from mcp.server.fastmcp import FastMCP

try:
    from . import research
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    import research


mcp = FastMCP(
    'Star Graph',
    instructions=(
        'Search and compare the user\'s starred GitHub repositories for new projects. '
        'Treat LLM-derived fields as suggestions and use the returned evidence and provenance.'
    ),
)


def limit(value, maximum=50):
    return max(1, min(int(value), maximum))


@mcp.tool()
def list_domains() -> list[dict[str, Any]]:
    """List supported research domains and their editable search aliases."""
    return [
        {'domain': domain, 'aliases': aliases}
        for domain, aliases in sorted(research.load_aliases().items())
    ]


@mcp.tool()
def search_domain(domain: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Find starred repositories for a domain such as cms or ai-harness."""
    graph = research.load_graph()
    results = research.search_repos(graph, domain, limit(top_k), domain=domain)
    return [
        {
            'repository': result['repo'],
            'url': result['attributes'].get('html_url', ''),
            'score': round(result['score'], 2),
            'why': result['reasons'],
            'language': result['attributes'].get('language') or 'Unknown',
            'stars': result['attributes'].get('stargazers_count', 0),
            'license': result['attributes'].get('license') or 'Unknown',
            'activity': research.activity(result['attributes']),
            'use_cases': sorted(research.values(result['attributes'].get('use_cases', []))),
        }
        for result in results
    ]


@mcp.tool()
def research_project(query: str, top_k: int = 10) -> str:
    """Create a Markdown research report for a project idea or technical question."""
    graph = research.load_graph()
    results = research.search_repos(graph, query, limit(top_k))
    return research.markdown_report(query, results)


@mcp.tool()
def compare_repositories(repositories: list[str]) -> str:
    """Compare selected owner/repo names by fit, activity, license, and use case."""
    if not repositories:
        raise ValueError('Provide at least one owner/repo name')
    return research.comparison_table(research.load_graph(), repositories[:10])


@mcp.tool()
def get_repository(repository: str) -> dict[str, Any]:
    """Return detailed metadata, enrichment, provenance, and research signals for one repo."""
    graph = research.load_graph()
    node = next(
        (
            node for node in research.repo_nodes(graph)
            if node['key'].lower() == repository.lower()
        ),
        None,
    )
    if not node:
        raise ValueError(f'Unknown starred repository: {repository}')

    attrs = node['attributes']
    self_hosting, self_hosting_reason = research.self_hosting(attrs)
    return {
        'repository': node['key'],
        'url': attrs.get('html_url', ''),
        'description': attrs.get('description', ''),
        'language': attrs.get('language') or 'Unknown',
        'license': attrs.get('license') or 'Unknown',
        'stars': attrs.get('stargazers_count', 0),
        'activity': research.activity(attrs),
        'archived': attrs.get('archived', False),
        'topics': sorted(research.values(attrs.get('all_topics', ''))),
        'tech_stack': sorted(research.values(attrs.get('tech_stack', []))),
        'use_cases': sorted(research.values(attrs.get('use_cases', []))),
        'maturity': attrs.get('maturity') or 'Unknown',
        'complexity': attrs.get('complexity_score') or 'Unknown',
        'self_hosting': self_hosting,
        'self_hosting_reason': self_hosting_reason,
        'enrichment': {
            'status': attrs.get('enrichment_status', 'Unknown'),
            'model': attrs.get('enrichment_model', 'Unknown'),
            'hash': attrs.get('enrichment_hash', ''),
            'enriched_at': attrs.get('enriched_at', ''),
        },
        'deep_research': {
            'status': attrs.get('deep_analysis_status', 'Unknown'),
            'model': attrs.get('deep_model', 'Unknown'),
            'analyzed_at': attrs.get('deep_analyzed_at', ''),
        },
    }


def main():
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
