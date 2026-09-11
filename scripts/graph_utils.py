#!/usr/bin/env python3
"""Shared utilities for star graph scripts.
Single source of truth for topic normalization and LLM output validation.
"""
import re


def normalize_topic(s):
    """Normalize a topic string to kebab-case.
    'AI Agents' -> 'ai-agents', 'web_scraping' -> 'web-scraping'
    """
    if not isinstance(s, str):
        return ''
    s = s.lower().strip()
    s = s.replace(' ', '-').replace('_', '-')
    s = re.sub(r'[^a-z0-9-]', '', s)
    s = re.sub(r'-+', '-', s)
    s = s.strip('-')
    return s


def validate_deep_analysis(data):
    """Validate and sanitize deep analysis LLM output.
    Returns a clean dict with correct types, or {} if input is garbage.
    """
    if not isinstance(data, dict):
        return {}

    result = {}

    topics = data.get('inferred_topics', [])
    result['inferred_topics'] = (
        [normalize_topic(t) for t in topics if isinstance(t, str) and normalize_topic(t)][:10]
        if isinstance(topics, list) else []
    )

    pp = data.get('primary_purpose', '')
    result['primary_purpose'] = str(pp)[:500] if pp else ''

    ts = data.get('tech_stack', [])
    result['tech_stack'] = (
        [normalize_topic(t) for t in ts if isinstance(t, str) and normalize_topic(t)][:15]
        if isinstance(ts, list) else []
    )

    ap = data.get('architecture_patterns', [])
    result['architecture_patterns'] = (
        [normalize_topic(a) for a in ap if isinstance(a, str) and normalize_topic(a)][:10]
        if isinstance(ap, list) else []
    )

    uc = data.get('use_cases', [])
    result['use_cases'] = (
        [normalize_topic(u) for u in uc if isinstance(u, str) and normalize_topic(u)][:10]
        if isinstance(uc, list) else []
    )

    maturity = str(data.get('maturity', '')).lower()
    result['maturity'] = maturity if maturity in ('experimental', 'active', 'stable', 'deprecated') else ''

    allowed_audiences = ('developers', 'data-scientists', 'devops', 'researchers', 'general')
    raw_audience = data.get('target_audience', '')
    audience_values = raw_audience if isinstance(raw_audience, list) else [raw_audience]
    result['target_audience'] = next(
        (str(a).lower() for a in audience_values if str(a).lower() in allowed_audiences),
        ''
    )

    uv = data.get('unique_value', '')
    result['unique_value'] = str(uv)[:500] if uv else ''

    deps = data.get('dependencies', [])
    result['dependencies'] = (
        [str(d) for d in deps if isinstance(d, str)][:20]
        if isinstance(deps, list) else []
    )

    try:
        cs = int(data.get('complexity_score', 0))
        result['complexity_score'] = max(1, min(10, cs))
    except (ValueError, TypeError):
        result['complexity_score'] = 0

    pr = data.get('production_ready', False)
    if isinstance(pr, str):
        result['production_ready'] = pr.lower() in ('true', 'yes', '1')
    else:
        result['production_ready'] = bool(pr)

    return result


def validate_inferred_topics(topics):
    """Validate a list of inferred topics from LLM enrichment."""
    if not isinstance(topics, list):
        return []
    result = []
    for t in topics:
        if isinstance(t, str):
            normalized = normalize_topic(t)
            if normalized:
                result.append(normalized)
    return result[:8]
