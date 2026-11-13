"""Immutable two-domain selections from genuine saved Google SERP observations.

Selections are deliberately not executed yet: downstream collectors must use
run-isolated evidence directories before arbitrary domain comparisons are safe.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import ipaddress
from urllib.parse import urlsplit, urlunsplit

from config.settings import ROOT
from collectors.tracked_serp import normalize_domain
from scripts.dashboard_serp_search import _snapshot_path, validate_keyword
from scripts.resolve_pages import normalized_url

INVESTIGATIONS = ROOT / 'data' / 'investigations'


def snapshot_fingerprint(keyword: str) -> str:
    path = _snapshot_path(validate_keyword(keyword))
    if not path.is_file():
        raise FileNotFoundError('No Google SERP snapshot for this keyword')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection_options(keyword: str) -> dict:
    from scripts.dashboard_serp_search import read_snapshot
    snapshot = read_snapshot(keyword)
    unique = {}
    for row in snapshot['organic_results']:
        domain = normalize_domain(row['domain'])
        if domain not in unique:
            unique[domain] = {'domain': domain, 'rank': row['rank_group'],
                              'url': row['url'], 'title': row['title']}
    return {'keyword': snapshot['keyword'], 'snapshot_fingerprint': snapshot_fingerprint(keyword),
            'collected_at': snapshot['collected_at'], 'options': list(unique.values())}


def create_investigation(keyword: str, first_domain: str, second_domain: str,
                         fingerprint: str) -> dict:
    keyword = validate_keyword(keyword)
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError('Missing or invalid SERP fingerprint. Reload the results.')
    if snapshot_fingerprint(keyword) != fingerprint:
        raise ValueError('SERP snapshot changed. Reload the latest results and select again.')
    options = selection_options(keyword)
    if options['snapshot_fingerprint'] != fingerprint:
        raise ValueError('SERP snapshot changed during selection. Reload the results.')
    domain_map = {r['domain']: r for r in options['options']}
    first = normalize_domain(first_domain)
    second = normalize_domain(second_domain)
    if first == second:
        raise ValueError('Select two different domains.')
    if first not in domain_map or second not in domain_map:
        raise ValueError('Both domains must appear in the saved Google SERP.')
    investigation_id = uuid.uuid4().hex
    manifest = {
        'schema_version': '1.0', 'investigation_id': investigation_id,
        'keyword': keyword, 'serp_sha256': fingerprint,
        'serp_collected_at': options['collected_at'],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'selected_not_analyzed',
        'ours': domain_map[first], 'benchmark': domain_map[second],
        'source': 'observed_google_playwright_serp',
        'note': 'Ranking URLs and ranks are captured SERP observations; no comparison has run.',
    }
    directory = INVESTIGATIONS / investigation_id
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / 'selection.json'
    with target.open('x', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def read_investigation(investigation_id: str) -> dict:
    if len(investigation_id) != 32 or any(c not in '0123456789abcdef' for c in investigation_id):
        raise ValueError('Invalid investigation ID')
    path = INVESTIGATIONS / investigation_id / 'selection.json'
    if not path.is_file():
        raise FileNotFoundError('Investigation not found')
    return json.loads(path.read_text(encoding='utf-8'))


def validate_public_page_url(value: object) -> tuple[str, str]:
    """Validate a manually entered page identity without fetching it."""
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2048:
        raise ValueError('Enter a complete HTTP(S) webpage URL (maximum 2048 characters).')
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in value.strip()):
        raise ValueError('Webpage URL cannot contain spaces or control characters.')
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Enter a public HTTP(S) webpage URL without credentials.')
    if parts.port is not None and parts.port not in (80, 443):
        raise ValueError('Only standard HTTP(S) ports are supported.')
    host = parts.hostname.lower().rstrip('.')
    if host in ('localhost',) or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
        raise ValueError('A public domain is required.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if any(not part or not all(c.isalnum() or c == '-' for c in part) or
               part.startswith('-') or part.endswith('-') for part in host.split('.')):
            raise ValueError('Invalid public domain.')
    else:
        raise ValueError('IP-address targets are not supported.')
    url = urlunsplit((parts.scheme.lower(), host + (f':{parts.port}' if parts.port else ''),
                      parts.path or '/', parts.query, ''))
    if not normalized_url(url):
        raise ValueError('Invalid webpage URL.')
    return url, normalize_domain(host)


def create_page_investigation(keyword: str, first_url: str, second_url: str,
                              fingerprint: str | None = None) -> dict:
    """Create a manual two-URL investigation; no network or model requests.

    A saved SERP is optional. Exact-page rankings are populated only from
    observed matching URLs, never inferred from another URL on the domain.
    """
    keyword = validate_keyword(keyword)
    first, first_domain = validate_public_page_url(first_url)
    second, second_domain = validate_public_page_url(second_url)
    if normalized_url(first) == normalized_url(second):
        raise ValueError('Enter two different webpage URLs.')
    snapshot = None
    sha = None
    path = _snapshot_path(keyword)
    if path.exists():
        sha = snapshot_fingerprint(keyword)
        if fingerprint is not None and fingerprint != sha:
            raise ValueError('SERP snapshot changed. Reload saved results before saving.')
        from scripts.dashboard_serp_search import read_snapshot
        snapshot = read_snapshot(keyword)
    elif fingerprint is not None:
        raise ValueError('No saved SERP exists for the supplied fingerprint.')

    def observed(url, domain):
        matches = [r for r in (snapshot or {}).get('organic_results', [])
                   if normalized_url(r.get('url')) == normalized_url(url)]
        row = matches[0] if matches else {}
        return {'domain': domain, 'url': url, 'rank': row.get('rank_group'),
                'title': row.get('title'), 'ranking_status': 'observed_exact_page' if row else 'not_observed_in_saved_serp'}

    investigation_id = uuid.uuid4().hex
    manifest = {'schema_version': '1.1', 'investigation_id': investigation_id,
                'keyword': keyword, 'serp_sha256': sha,
                'serp_collected_at': (snapshot or {}).get('collected_at'),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'status': 'selected_not_analyzed',
                'ours': observed(first, first_domain),
                'benchmark': observed(second, second_domain),
                'source': 'manual_exact_webpage_urls',
                'note': 'No requests executed. An absent page rank is unknown within the saved observation, not a zero ranking.'}
    from scripts.investigation_offline import evidence_inventory
    directory = INVESTIGATIONS / investigation_id
    directory.mkdir(parents=True, exist_ok=False)
    inventory = evidence_inventory(manifest)
    manifest['offline_evidence_summary'] = {'available': inventory['available'],
        'total': inventory['required_evidence_items'], 'complete': inventory['complete']}
    (directory / 'selection.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'offline_evidence.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def read_offline_evidence(investigation_id: str) -> dict:
    read_investigation(investigation_id)
    path = INVESTIGATIONS / investigation_id / 'offline_evidence.json'
    if not path.is_file():
        raise FileNotFoundError('No offline evidence inventory for this investigation')
    return json.loads(path.read_text(encoding='utf-8'))
