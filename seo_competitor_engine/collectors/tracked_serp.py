"""Bounded, evidence-preserving tracked-domain discovery in observed Google SERPs.

This module never changes the order or rank of scraped results and never
retries a query in order to obtain a preferred position.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def normalize_domain(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Tracked domain must be a string')
    value = value.strip().lower()
    if not value:
        raise ValueError('Tracked domain cannot be empty')
    if '://' in value:
        host = urlsplit(value).hostname or ''
    else:
        host = value.strip('.').split('/')[0].split(':')[0]
    host = host.removeprefix('www.')
    if not host or '.' not in host or any(ch.isspace() for ch in host):
        raise ValueError('Invalid tracked domain')
    return host


def domain_matches(observed: str, tracked: str) -> bool:
    """Allow subdomains, but never suffix collisions (fakehollywoodbets.net)."""
    observed = (observed or '').lower().strip('.').removeprefix('www.')
    tracked = normalize_domain(tracked)
    return observed == tracked or observed.endswith('.' + tracked)


def tracked_position(rows: list[dict], domain: str) -> dict | None:
    """Find the first observed organic listing for a domain; do not mutate rows."""
    for index, row in enumerate(rows):
        if domain_matches(row.get('domain', ''), domain):
            return {'rank': index + 1, 'domain': row['domain'], 'url': row.get('url'), 'title': row.get('title')}
    return None


def discovery_state(rows: list[dict], tracked_domain: str, minimum_results: int,
                    maximum_results: int, neighbour_results: int = 2) -> dict:
    """Decision from *observed* sequence, not a manufactured SERP position."""
    found = tracked_position(rows, tracked_domain)
    enough_minimum = len(rows) >= minimum_results
    enough_neighbours = bool(found and len(rows) - found['rank'] >= neighbour_results)
    complete = enough_minimum and bool(found) and enough_neighbours
    return {
        'domain': normalize_domain(tracked_domain),
        'status': 'found' if found else 'not_found',
        'rank': found['rank'] if found else None,
        'ranking_url': found['url'] if found else None,
        'ranking_title': found['title'] if found else None,
        'results_above': found['rank'] - 1 if found else None,
        'results_below': len(rows) - found['rank'] if found else None,
        'minimum_results': minimum_results,
        'maximum_results': maximum_results,
        'neighbours_requested': neighbour_results,
        'complete': complete,
        'search_exhausted': len(rows) >= maximum_results,
        'rank_semantics': 'observed_organic_sequence; not guaranteed absolute Google rank',
    }
