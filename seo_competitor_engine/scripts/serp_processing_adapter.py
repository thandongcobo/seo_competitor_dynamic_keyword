"""Validate saved-SERP provenance before offline SEO processing.

This adapter is read-only. It does not search, rank, collect, or change a
selection's source; the existing processor remains responsible for evidence
inventory, artifact hashes, calculations, and reporting.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from config.settings import ROOT
from collectors.tracked_serp import domain_matches
from scripts import dashboard_serp_search, serp_investigations

IDEMPOTENCY_DIR = ROOT / 'data' / 'investigation_workflows' / 'hollywoodbets_compare_requests'
SEARCH_CONTEXT_FIELDS = (
    'status', 'collected_at', 'search_url', 'location_note', 'depth_requested',
    'depth_collected', 'pages_completed', 'stop_reason', 'maximum_search_depth',
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _aware_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f'Saved SERP investigation has an invalid {name}.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'Saved SERP investigation has an invalid {name}.') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'Saved SERP investigation has a timezone-free {name}.')
    return parsed.astimezone(timezone.utc)


def _selection_checkpoint_matches(investigation_id: str, selection_path: Path) -> bool:
    checkpoint_path = selection_path.parent / 'workflow' / 'checkpoint.json'
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
        stage = checkpoint['stages']['webpage_selection']
        if (checkpoint.get('investigation_id') != investigation_id or
                stage.get('status') != 'completed'):
            return False
        actual_sha = _sha(selection_path)
        return any(
            str(item.get('path', '')).replace('\\', '/').lstrip('./') == 'selection.json' and
            item.get('sha256') == actual_sha
            for item in stage.get('outputs', []) if isinstance(item, dict)
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _request_record_matches(selection: dict) -> bool:
    request = {
        'keyword': selection['keyword'],
        'snapshot_sha256': selection['serp_sha256'],
        'primary_url': selection['ours']['url'],
        'competitor_url': selection['benchmark']['url'],
        'parent_investigation_id': selection.get('parent_investigation_id'),
    }
    expected_fingerprint = _canonical_sha(request)
    try:
        paths = sorted(IDEMPOTENCY_DIR.glob('*.json'))
    except OSError:
        return False
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            continue
        if (record.get('investigation_id') == selection.get('investigation_id') and
                record.get('status') == 'completed' and
                record.get('request_fingerprint') == expected_fingerprint):
            return True
    return False


def _exact_result(snapshot: dict, page: dict, side: str) -> tuple[int, dict]:
    if not isinstance(page, dict):
        raise ValueError(f'Saved SERP investigation is missing its {side} page identity.')
    url = page.get('url')
    if not isinstance(url, str) or not url:
        raise ValueError(f'Saved SERP investigation has no exact {side} URL.')
    try:
        _, url_domain = serp_investigations.validate_public_page_url(url)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Saved SERP investigation has an invalid {side} URL.') from exc
    rows = snapshot.get('organic_results')
    if not isinstance(rows, list):
        raise ValueError('Saved SERP has no valid organic result list.')
    matches = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get('url') != url:
            continue
        rank = row.get('rank_group')
        domain = row.get('domain')
        if type(rank) is int and rank > 0 and isinstance(domain, str):
            matches.append((index, row, rank, domain))
    if len(matches) != 1:
        raise ValueError(f'The exact {side} URL is absent or ambiguous in the saved SERP.')
    index, row, rank, domain = matches[0]
    if type(page.get('rank')) is not int or page['rank'] != rank:
        raise ValueError(f'The saved SERP {side} position does not match the selected result.')
    if page.get('domain') != domain or not domain_matches(url_domain, domain):
        raise ValueError(f'The saved SERP {side} domain does not match its exact URL.')
    if 'result_index' in page and (type(page.get('result_index')) is not int or page['result_index'] != index):
        raise ValueError(f'The saved SERP {side} result index does not match its exact URL.')
    if 'title' in page and page.get('title') != row.get('title'):
        raise ValueError(f'The saved SERP {side} title does not match its exact URL.')
    return index, row


def validate_serp_origin_investigation(investigation_id: str) -> dict:
    """Return the saved selection only if its SERP provenance remains verified.

    The completed webpage-selection checkpoint pins the immutable selection
    file. The comparison idempotency record independently binds the ID, keyword,
    snapshot hash, exact URLs, and parent branch to a completed selection.
    """
    if not isinstance(investigation_id, str) or len(investigation_id) != 32 or any(
            char not in '0123456789abcdef' for char in investigation_id):
        raise ValueError('Invalid SERP investigation ID.')
    selection = serp_investigations.read_investigation(investigation_id)
    if selection.get('investigation_id') != investigation_id:
        raise ValueError('SERP investigation ID does not match its selection record.')
    if (selection.get('source') != 'observed_google_playwright_serp' or
            selection.get('selection_method') != 'hollywoodbets_first_saved_serp' or
            selection.get('selection_origin') != 'saved_google_serp_snapshot'):
        raise ValueError('Investigation does not use the verified saved-SERP source contract.')

    keyword = dashboard_serp_search.validate_keyword(selection.get('keyword'))
    snapshot_path = dashboard_serp_search._snapshot_path(keyword)
    if not snapshot_path.is_file():
        raise ValueError('The saved SERP snapshot referenced by this investigation is missing.')
    before = _sha(snapshot_path)
    snapshot = dashboard_serp_search.read_snapshot(keyword)
    after = _sha(snapshot_path)
    if before != after:
        raise ValueError('The saved SERP snapshot changed during validation.')
    if selection.get('serp_sha256') != before:
        raise ValueError('The saved SERP snapshot SHA-256 does not match the investigation.')
    if snapshot.get('keyword', '').casefold() != keyword.casefold():
        raise ValueError('The saved SERP keyword does not match the investigation.')

    expected_reference = str(snapshot_path.resolve().relative_to(ROOT.resolve())).replace('\\', '/')
    if selection.get('serp_snapshot_reference') != expected_reference:
        raise ValueError('The saved SERP snapshot reference does not match its keyword path.')
    expected_context = {key: snapshot.get(key) for key in SEARCH_CONTEXT_FIELDS}
    if selection.get('search_context') != expected_context:
        raise ValueError('The saved search context does not match the immutable SERP snapshot.')
    if selection.get('serp_collected_at') != snapshot.get('collected_at'):
        raise ValueError('The saved SERP search timestamp does not match the immutable snapshot.')
    created_at = _aware_datetime(selection.get('created_at'), 'selection timestamp')
    selected_at = _aware_datetime(selection.get('selection_created_at'), 'selection timestamp')
    collected_at = _aware_datetime(snapshot.get('collected_at'), 'SERP search timestamp')
    if created_at != selected_at or selected_at < collected_at:
        raise ValueError('The selection timestamp is inconsistent with the saved SERP search time.')

    tracked = snapshot.get('tracked_site')
    identity = selection.get('hollywoodbets_identification')
    if not isinstance(tracked, dict) or tracked.get('status') != 'found':
        raise ValueError('Hollywoodbets was not verified in the saved SERP.')
    if not domain_matches(tracked.get('domain', ''), 'hollywoodbets.net'):
        raise ValueError('The saved SERP tracked-site identity is not Hollywoodbets.')
    if (not isinstance(identity, dict) or identity.get('domain') != tracked.get('domain') or
            identity.get('default_rank') != tracked.get('rank') or
            identity.get('default_url') != tracked.get('ranking_url')):
        raise ValueError('Hollywoodbets identification metadata does not match the saved SERP.')
    _, tracked_row = _exact_result(snapshot, {
        'url': tracked.get('ranking_url'), 'rank': tracked.get('rank'),
        'domain': tracked.get('domain'), 'title': tracked.get('ranking_title'),
    }, 'tracked Hollywoodbets')
    if not domain_matches(tracked_row.get('domain', ''), 'hollywoodbets.net'):
        raise ValueError('The saved tracked-site result is not an observed Hollywoodbets page.')

    _, ours_row = _exact_result(snapshot, selection.get('ours'), 'Hollywoodbets')
    _, competitor_row = _exact_result(snapshot, selection.get('benchmark'), 'competitor')
    if not domain_matches(ours_row.get('domain', ''), 'hollywoodbets.net'):
        raise ValueError('The selected primary URL is not an observed Hollywoodbets result.')
    if domain_matches(competitor_row.get('domain', ''), 'hollywoodbets.net'):
        raise ValueError('The selected competitor URL is another Hollywoodbets result.')
    if selection['ours']['url'] == selection['benchmark']['url']:
        raise ValueError('Hollywoodbets and competitor webpages must be different.')

    selection_path = serp_investigations.INVESTIGATIONS / investigation_id / 'selection.json'
    if not _selection_checkpoint_matches(investigation_id, selection_path):
        raise ValueError('The immutable webpage-selection checkpoint is missing or does not match this record.')
    if not _request_record_matches(selection):
        raise ValueError('No completed comparison request record matches this immutable SERP selection.')
    return selection
