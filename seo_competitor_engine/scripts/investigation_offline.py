"""Offline-only evidence inventory for manually selected ranking pages.

Reads existing files. Never imports API clients, launches a browser, or calls an LLM.
Every 'available' item must have verifiable source target metadata.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from config.settings import ROOT, keyword_slug
from scripts.resolve_pages import normalized_url


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _ok_api(raw: dict | None) -> bool:
    return bool(raw and raw.get('status_code') == 20000 and
                any(isinstance(t, dict) and t.get('status_code') == 20000 for t in raw.get('tasks', [])))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_inventory(selection: dict, root: Path = ROOT) -> dict:
    keyword = selection['keyword']
    slug = keyword_slug(keyword)
    raw = root / 'data' / 'raw'
    entries = []

    def add(kind: str, side: str | None, candidates: list[Path], verifier) -> None:
        for path in candidates:
            payload = _load(path)
            if payload is not None and verifier(path, payload):
                entries.append({'kind': kind, 'side': side, 'status': 'available',
                                'path': str(path.relative_to(root)).replace('\\', '/'),
                                'sha256': _sha(path), 'source': 'saved_real_evidence'})
                return
        entries.append({'kind': kind, 'side': side, 'status': 'missing_or_target_mismatch',
                        'path': None, 'sha256': None})

    for side in ('ours', 'benchmark'):
        domain = selection[side]['domain']
        url = selection[side]['url']
        def labs_match(path, j, domain=domain):
            return _ok_api(j) and any(
                (t.get('data') or {}).get('target', '').lower().removeprefix('www.') == domain
                for t in j.get('tasks', []) if isinstance(t, dict))
        add('labs_ranked_keywords', side,
            sorted((raw / 'labs').glob(f'{slug}_ranked_*.json')), labs_match)

        for level, target in (('domain', domain), ('page', url)):
            def backlinks_match(path, j, level=level, target=target):
                meta = _load(path.with_suffix('.meta.json')) or {}
                if not _ok_api(j) or meta.get('keyword') != keyword or meta.get('scope') != level:
                    return False
                if level == 'page':
                    return normalized_url(meta.get('target')) == normalized_url(target)
                return str(meta.get('target', '')).lower().removeprefix('www.') == target
            add(f'backlinks_{level}_summary', side,
                sorted((raw / 'backlinks').glob(f'{slug}_*_{level}_summary.json')),
                backlinks_match)

        def page_match(path, j, url=url):
            return (j.get('keyword') == keyword and
                    normalized_url(j.get('ranking_url') or j.get('requested_url')) == normalized_url(url) and
                    normalized_url(j.get('requested_url')) == normalized_url(url))
        add('playwright_page', side,
            sorted((raw / 'pages').glob(f'{slug}_google_*.json')), page_match)

        def lighthouse_match(path, j, url=url):
            return (bool(j.get('lighthouseVersion')) and
                    normalized_url(j.get('requestedUrl')) == normalized_url(url))
        add('lighthouse_mobile', side,
            sorted((raw / 'lighthouse').glob(f'{slug}_google_*_mobile.json')),
            lighthouse_match)

    domains = {selection['ours']['domain'], selection['benchmark']['domain']}
    def intersection_match(path, j):
        return _ok_api(j) and any(
            {(t.get('data') or {}).get('target1'), (t.get('data') or {}).get('target2')} == domains
            for t in j.get('tasks', []) if isinstance(t, dict))
    add('labs_domain_intersection', None,
        [raw / 'labs' / f'{slug}_domain_intersection.json'], intersection_match)

    def intent_match(path, j):
        return _ok_api(j) and any(keyword.lower() in [str(k).lower() for k in (t.get('data') or {}).get('keywords', [])]
                                  for t in j.get('tasks', []) if isinstance(t, dict))
    add('labs_search_intent', None,
        [raw / 'labs' / f'{slug}_search_intent.json'], intent_match)

    available = sum(e['status'] == 'available' for e in entries)
    return {'schema_version': '1.0', 'investigation_id': selection['investigation_id'],
            'keyword': keyword, 'mode': 'offline_inventory_only', 'requests_made': 0,
            'available': available, 'required_evidence_items': len(entries),
            'complete': available == len(entries), 'entries': entries,
            'note': 'Inventory checks saved source metadata only. It does not run analysis or validate live freshness.'}
