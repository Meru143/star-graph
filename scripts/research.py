"""Search, report on, and compare starred repositories for new projects."""
import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent.parent
GRAPH_FILE = ROOT / 'data' / 'star_graph_enhanced.json'
ALIASES_FILE = ROOT / 'data' / 'domain_aliases.json'
TOKEN_RE = re.compile(r'[a-z0-9]+')
STOPWORDS = {
    'about', 'and', 'app', 'build', 'building', 'for', 'from', 'help', 'how',
    'i', 'into', 'my', 'need', 'project', 'should', 'the', 'this', 'want',
    'with', 'you', 'your'
}
SHORT_TERMS = {'ai', 'baas', 'cms', 'css', 'js', 'mcp', 'ui', 'ux'}
FIELD_WEIGHTS = {
    'topics': 5,
    'tech_stack': 5,
    'use_cases': 4,
    'purpose': 3,
    'architecture': 2,
    'description': 2,
    'audience': 1,
}
DOMAIN_SIGNAL_TERMS = {
    'cms': 'cms headless strapi directus payload sanity keystone ghost wordpress tina contentful',
    'ai-harness': 'harness mcp langgraph autogen crew agents agent orchestration',
    'backend-platform': 'baas supabase appwrite firebase pocketbase backend serverless database api',
    'frontend': 'frontend react nextjs vue svelte angular tailwind css component design ui ux',
}
DOMAIN_QUERY_HINTS = {
    'cms': 'content publishing headless blog documentation knowledge',
    'ai-harness': 'agent harness llm orchestration coding mcp',
    'backend-platform': 'backend database serverless api platform baas',
    'frontend': 'frontend react nextjs vue svelte ui ux design css',
}


def load_graph():
    with open(GRAPH_FILE, encoding='utf-8') as handle:
        return json.load(handle)


def load_aliases():
    with open(ALIASES_FILE, encoding='utf-8') as handle:
        return json.load(handle)


def normalize_text(value):
    text = str(value or '').lower()
    text = text.replace('next.js', 'nextjs').replace('front-end', 'frontend')
    return text.replace('_', ' ').replace('-', ' ')


def tokens(value):
    return {
        token for token in TOKEN_RE.findall(normalize_text(value))
        if token not in STOPWORDS and (len(token) >= 3 or token in SHORT_TERMS)
    }


def values(value):
    if isinstance(value, str):
        return {item for item in value.split('|') if item}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str) and item}
    return set()


def profile(attrs):
    return {
        'topics': values(attrs.get('explicit_topics', '')) | values(attrs.get('inferred_topics', [])),
        'tech_stack': values(attrs.get('tech_stack', [])),
        'use_cases': values(attrs.get('use_cases', [])),
        'purpose': {attrs.get('primary_purpose', '') or ''},
        'architecture': values(attrs.get('architecture_patterns', [])),
        'description': {attrs.get('description', '') or ''},
        'audience': {attrs.get('target_audience', '') or ''},
    }


def repo_nodes(graph):
    return [
        node for node in graph['nodes']
        if node.get('attributes', {}).get('type') == 'repo'
    ]


def canonical_domain(name, aliases):
    key = normalize_text(name).replace(' ', '-')
    return key if key in aliases else None


def search_terms(query, aliases):
    query_tokens = tokens(query)
    matched_domains = []
    normalized_query = normalize_text(query)
    query_token_set = tokens(query)
    for domain, domain_aliases in aliases.items():
        candidates = [domain] + domain_aliases
        hint_tokens = tokens(DOMAIN_QUERY_HINTS.get(domain, ''))
        if (
            any(normalize_text(alias) in normalized_query for alias in candidates)
            or query_token_set & hint_tokens
        ):
            matched_domains.append(domain)
            for alias in candidates:
                query_tokens.update(tokens(alias))
    return query_tokens, matched_domains


def domain_search_terms(domain, aliases):
    key = canonical_domain(domain, aliases)
    if not key:
        raise ValueError(f"Unknown domain '{domain}'. Available: {', '.join(sorted(aliases))}")
    terms = set(tokens(key))
    for alias in aliases[key]:
        terms.update(tokens(alias))
    return key, terms


def search_repos(graph, query, top_k=10, domain=None):
    aliases = load_aliases()
    if domain:
        domain, terms = domain_search_terms(domain, aliases)
        matched_domains = [domain]
    else:
        terms, matched_domains = search_terms(query, aliases)

    repos = repo_nodes(graph)
    field_sets = {
        node['key']: {
            field: tokens(' '.join(profile(node['attributes'])[field]))
            for field in FIELD_WEIGHTS
        }
        for node in repos
    }
    document_frequency = Counter(
        (field, term)
        for fields in field_sets.values()
        for field in FIELD_WEIGHTS
        for term in fields[field]
    )

    results = []
    for node in repos:
        name = node['key']
        fields = field_sets[name]
        if domain:
            signal_terms = tokens(DOMAIN_SIGNAL_TERMS.get(domain, domain))
            if not signal_terms & set().union(*fields.values()):
                continue
        score = 0.0
        reasons = []
        for field, weight in FIELD_WEIGHTS.items():
            overlap = terms & fields[field]
            if not overlap:
                continue
            score += sum(
                weight * (math.log((len(repos) + 1) / (document_frequency[(field, term)] + 1)) + 1)
                for term in overlap
            )
            reasons.append(f"{field}: {', '.join(sorted(overlap)[:5])}")
        if score:
            attrs = node['attributes']
            score += math.log1p(float(attrs.get('stargazers_count', 0) or 0)) / 100
            results.append({
                'repo': name,
                'score': score,
                'reasons': reasons,
                'matched_domains': matched_domains,
                'attributes': attrs,
            })

    results.sort(key=lambda result: (-result['score'], -result['attributes'].get('stargazers_count', 0), result['repo']))
    return results[:top_k]


def clean(value, limit=240):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text[:limit] + ('…' if len(text) > limit else '')


def activity(attrs):
    pushed = attrs.get('pushed_at', '')
    if not pushed:
        return 'Unknown activity'
    try:
        date = datetime.fromisoformat(pushed.replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - date).days
    except ValueError:
        return f'Last pushed {pushed[:10]}'
    if attrs.get('archived'):
        label = 'Archived'
    elif age <= 90:
        label = 'Active'
    elif age <= 365:
        label = 'Recent'
    else:
        label = 'Stale'
    return f'{label}; last pushed {pushed[:10]}'


def self_hosting(attrs):
    text = normalize_text(' '.join([
        attrs.get('description', ''), attrs.get('primary_purpose', ''),
        attrs.get('all_topics', '') or '',
        ' '.join(values(attrs.get('explicit_topics', ''))),
        ' '.join(values(attrs.get('inferred_topics', []))),
        ' '.join(values(attrs.get('use_cases', []))),
        ' '.join(values(attrs.get('tech_stack', []))),
    ]))
    likely = ('self host', 'on prem', 'on premise', 'docker', 'kubernetes', 'local first', 'deploy')
    hosted = ('saas', 'cloud only', 'managed service')
    if any(term in text for term in likely):
        return 'Likely', 'self-hosting signal found in metadata'
    if any(term in text for term in hosted):
        return 'Unclear', 'hosted-service signal found; verify deployment options'
    return 'Unknown', 'no self-hosting signal in available metadata'


def markdown_report(query, results):
    matched_domains = sorted({
        domain for result in results for domain in result.get('matched_domains', [])
    })
    lines = [
        '# Project Research Report',
        '',
        f'**Question:** {query}',
        f'**Generated:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
    ]
    if matched_domains:
        lines.append(f'**Recognized domains:** {", ".join(matched_domains)} (aliases expanded)')
    lines.extend([
        '',
        'Matches use GitHub metadata and cached enrichment. Scores are a shortlist signal, not a final technical judgment.',
        '',
        '## Candidates',
        '',
    ])
    for index, result in enumerate(results, 1):
        attrs = result['attributes']
        self_host, self_host_reason = self_hosting(attrs)
        lines.extend([
            f'### {index}. [{result["repo"]}]({attrs.get("html_url", "")})',
            f'- Match score: `{result["score"]:.2f}`',
            f'- Why it matched: {"; ".join(result["reasons"])}',
            f'- Description: {clean(attrs.get("description", "")) or "No description"}',
            f'- Language: {attrs.get("language") or "Unknown"}',
            f'- Tech stack: {", ".join(sorted(values(attrs.get("tech_stack", [])))) or "Unknown"}',
            f'- Stars: {attrs.get("stargazers_count", 0):,}',
            f'- License: {attrs.get("license") or "Unknown"}',
            f'- Activity: {activity(attrs)}',
            f'- Maturity: {attrs.get("maturity") or "Unknown"}',
            f'- Self-hosting: {self_host} ({self_host_reason})',
            f'- Complexity: {attrs.get("complexity_score") or "Unknown"}/10',
            f'- Use cases: {", ".join(sorted(values(attrs.get("use_cases", [])))) or "Unknown"}',
            '',
        ])
    if not results:
        lines.extend(['No matching repositories found.', ''])
    return '\n'.join(lines)


def comparison_table(graph, repo_names):
    nodes = {node['key']: node['attributes'] for node in repo_nodes(graph)}
    missing = [name for name in repo_names if name not in nodes]
    if missing:
        raise ValueError(f"Unknown repo(s): {', '.join(missing)}")

    rows = {
        'Language': lambda attrs: attrs.get('language') or 'Unknown',
        'License': lambda attrs: attrs.get('license') or 'Unknown',
        'Stars': lambda attrs: f"{attrs.get('stargazers_count', 0):,}",
        'Activity': activity,
        'Maturity': lambda attrs: attrs.get('maturity') or 'Unknown',
        'Self-hosting': lambda attrs: f'{self_hosting(attrs)[0]} — {self_hosting(attrs)[1]}',
        'Complexity': lambda attrs: f"{attrs.get('complexity_score')}/10" if attrs.get('complexity_score') else 'Unknown',
        'Use cases': lambda attrs: ', '.join(sorted(values(attrs.get('use_cases', [])))) or 'Unknown',
        'Primary purpose': lambda attrs: clean(attrs.get('primary_purpose', '')) or clean(attrs.get('description', '')) or 'Unknown',
    }
    headers = ['Criterion'] + repo_names
    lines = [
        '# Candidate Comparison',
        '',
        '| ' + ' | '.join(headers) + ' |',
        '| ' + ' | '.join(['---'] * len(headers)) + ' |',
    ]
    for criterion, getter in rows.items():
        cells = [criterion] + [clean(getter(nodes[name])).replace('|', '\\|') for name in repo_names]
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines.extend(['', 'Self-hosting is a transparent metadata heuristic; verify the repository documentation before choosing.', ''])
    return '\n'.join(lines)


def write_or_print(content, output):
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        print(f'Wrote {path}')
    else:
        print(content)


def main():
    parser = argparse.ArgumentParser(description='Research your starred repositories for a new project.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    search = subparsers.add_parser('search', help='Search a domain using aliases')
    search.add_argument('--domain', required=True, help='Example: cms, ai-harness, backend-platform, frontend')
    search.add_argument('--top-k', type=int, default=10)

    report = subparsers.add_parser('report', help='Write a Markdown project research report')
    report.add_argument('--query', required=True, help='Project question or brief')
    report.add_argument('--top-k', type=int, default=10)
    report.add_argument('--output', help='Markdown output path; otherwise print to stdout')

    compare = subparsers.add_parser('compare', help='Compare selected repositories')
    compare.add_argument('--repos', required=True, help='Comma-separated owner/repo names')
    compare.add_argument('--output', help='Markdown output path; otherwise print to stdout')

    args = parser.parse_args()
    graph = load_graph()
    try:
        if args.command == 'search':
            aliases = load_aliases()
            domain, _ = domain_search_terms(args.domain, aliases)
            results = search_repos(graph, domain, args.top_k, domain=domain)
            print(f'Domain: {domain} (aliases expanded)')
            for index, result in enumerate(results, 1):
                attrs = result['attributes']
                print(f'{index}. {result["repo"]} — {result["score"]:.2f} — {attrs.get("language") or "Unknown"} — {attrs.get("stargazers_count", 0):,} stars')
                print(f'   Why: {"; ".join(result["reasons"])}')
        elif args.command == 'report':
            results = search_repos(graph, args.query, args.top_k)
            write_or_print(markdown_report(args.query, results), args.output)
        else:
            repo_names = [name.strip() for name in args.repos.split(',') if name.strip()]
            write_or_print(comparison_table(graph, repo_names), args.output)
    except ValueError as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
