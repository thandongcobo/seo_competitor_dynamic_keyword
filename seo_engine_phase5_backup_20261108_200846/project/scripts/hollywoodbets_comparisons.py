"""Saved-SERP-only Hollywoodbets-first comparison selection adapter.

This module consumes the existing SERP snapshot and tracked-site decision. It
does not search, rank, crawl, or analyze. Compare persists a new exact-page
investigation and initializes the Phase 1/1.1 workflow only.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from config.settings import ROOT
from collectors.tracked_serp import domain_matches
from scripts import dashboard_serp_search, investigation_offline, investigation_workflow
from scripts import serp_investigations
from scripts.resolve_pages import normalized_url

INVESTIGATIONS = serp_investigations.INVESTIGATIONS
_IDEMPOTENCY_DIR = ROOT / 'data' / 'investigation_workflows' / 'hollywoodbets_compare_requests'
_LOCK_PATH = ROOT / 'data' / 'investigation_workflows' / 'hollywoodbets_compare.lock'
HOLLYWOODBETS_NOT_FOUND = 'Hollywoodbets was not found in the returned organic search results for this keyword.'


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha(value: dict) -> str:
    return _sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode('utf-8'))


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _compare_lock(timeout: float = 20):
    """A small cross-process lock around idempotency reservation and creation."""
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, json.dumps({'pid': os.getpid(), 'created_at': _utc()}).encode('utf-8'))
        except FileExistsError:
            try:
                lock = json.loads(_LOCK_PATH.read_text(encoding='utf-8'))
                pid = int(lock.get('pid', -1))
                try:
                    os.kill(pid, 0)
                    alive = True
                except (OSError, ValueError):
                    alive = False
                if not alive:
                    _LOCK_PATH.unlink(missing_ok=True)
                    continue
            except (OSError, ValueError, TypeError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Another comparison is being created. Try again shortly.')
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        _LOCK_PATH.unlink(missing_ok=True)


def _snapshot(keyword: str) -> tuple[dict, str, str]:
    keyword = dashboard_serp_search.validate_keyword(keyword)
    path = dashboard_serp_search._snapshot_path(keyword)
    if not path.is_file():
        raise FileNotFoundError('No saved Google results exist for this keyword. Search or load a saved snapshot first.')
    before = _sha_bytes(path.read_bytes())
    snapshot = dashboard_serp_search.read_snapshot(keyword)
    after = _sha_bytes(path.read_bytes())
    if before != after:
        raise ValueError('The saved SERP changed while it was being read. Reload the results before selecting pages.')
    return snapshot, before, str(path.relative_to(ROOT)).replace('\\', '/')


def _rank(row: dict) -> int | None:
    value = row.get('rank_group')
    return value if type(value) is int and value > 0 else None


def _page_option(row: dict, index: int, tracked_domain: str) -> dict | None:
    url, domain = row.get('url'), row.get('domain')
    if not isinstance(url, str) or not isinstance(domain, str) or _rank(row) is None:
        return None
    try:
        # Validate that the observed URL is safe and public, but retain the
        # exact unmodified SERP URL as the selection identity.
        serp_investigations.validate_public_page_url(url)
    except (ValueError, TypeError):
        return None
    return {'result_index': index, 'domain': domain, 'rank': row['rank_group'],
            'title': row.get('title'), 'url': url,
            'is_hollywoodbets': domain_matches(domain, tracked_domain)}


def selection_options(keyword: str) -> dict:
    snapshot, fingerprint, reference = _snapshot(keyword)
    context = {key: snapshot.get(key) for key in (
        'status', 'collected_at', 'search_url', 'location_note', 'depth_requested',
        'depth_collected', 'pages_completed', 'stop_reason', 'maximum_search_depth')}
    tracked = snapshot.get('tracked_site')
    if not isinstance(tracked, dict) or not tracked.get('domain') or tracked.get('status') not in ('found', 'not_found'):
        return {'status': 'selection_error', 'keyword': snapshot['keyword'],
                'message': 'Hollywoodbets identification is unavailable or ambiguous in this saved SERP. No comparison target was guessed.',
                'snapshot_sha256': fingerprint, 'snapshot_reference': reference,
                'search_context': context}
    try:
        is_hollywoodbets = domain_matches(tracked['domain'], 'hollywoodbets.net')
    except (ValueError, TypeError):
        is_hollywoodbets = False
    if not is_hollywoodbets:
        return {'status': 'selection_error', 'keyword': snapshot['keyword'],
                'message': 'The saved SERP tracked-site configuration is not Hollywoodbets. A Hollywoodbets-first comparison cannot be selected from this snapshot.',
                'snapshot_sha256': fingerprint, 'snapshot_reference': reference,
                'search_context': context, 'tracked_site': tracked}
    if tracked['status'] == 'not_found':
        return {'status': 'hollywoodbets_not_found', 'keyword': snapshot['keyword'],
                'message': HOLLYWOODBETS_NOT_FOUND, 'snapshot_sha256': fingerprint,
                'snapshot_reference': reference, 'search_context': context,
                'tracked_site': tracked, 'primary_options': [],
                'competitor_options': []}

    rows = snapshot.get('organic_results')
    if not isinstance(rows, list) or not rows:
        return {'status': 'selection_error', 'keyword': snapshot['keyword'],
                'message': 'The saved SERP has no usable organic result list. No comparison target was guessed.',
                'snapshot_sha256': fingerprint, 'snapshot_reference': reference,
                'search_context': context}
    primary_options = []
    competitor_options = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        option = _page_option(row, index, tracked['domain'])
        if not option:
            continue
        if option['is_hollywoodbets']:
            primary_options.append(option)
        else:
            competitor_options.append(option)
    if not primary_options:
        return {'status': 'selection_error', 'keyword': snapshot['keyword'],
                'message': 'The saved Hollywoodbets identification does not match a valid organic result URL and position. Reload the saved results; no target was guessed.',
                'snapshot_sha256': fingerprint, 'snapshot_reference': reference,
                'tracked_site': tracked, 'primary_options': [], 'competitor_options': competitor_options}
    default = primary_options[0]
    if (normalized_url(tracked.get('ranking_url')) != normalized_url(default['url']) or
            tracked.get('rank') != default['result_index'] + 1):
        return {'status': 'selection_error', 'keyword': snapshot['keyword'],
                'message': 'Hollywoodbets identification conflicts with the highest-ranking observed Hollywoodbets result. No comparison target was guessed.',
                'snapshot_sha256': fingerprint, 'snapshot_reference': reference,
                'tracked_site': tracked, 'primary_options': primary_options,
                'competitor_options': competitor_options}
    return {'status': 'ready' if competitor_options else 'no_eligible_competitors',
            'keyword': snapshot['keyword'], 'snapshot_sha256': fingerprint,
            'snapshot_reference': reference, 'search_context': context,
            'tracked_site': tracked, 'primary_options': primary_options,
            'default_primary_url': default['url'], 'competitor_options': competitor_options,
            'organic_results_count': len(rows)}


def _selection_record(investigation_id: str, options: dict, primary: dict,
                      competitor: dict, parent_id: str | None) -> dict:
    selected_at = _utc()
    def identity(row: dict) -> dict:
        return {'domain': row['domain'], 'url': row['url'], 'rank': row['rank'],
                'title': row.get('title'), 'result_index': row['result_index'],
                # These values are unknown until a page collector observes them.
                'redirect_url': None, 'canonical_url': None}
    return {'schema_version': '2.0', 'investigation_id': investigation_id,
            'keyword': options['keyword'], 'serp_sha256': options['snapshot_sha256'],
            'serp_snapshot_reference': options['snapshot_reference'],
            'serp_collected_at': options['search_context'].get('collected_at'),
            'search_context': options['search_context'], 'created_at': selected_at,
            'selection_created_at': selected_at, 'selection_method': 'hollywoodbets_first_saved_serp',
            'source': 'observed_google_playwright_serp', 'selection_origin': 'saved_google_serp_snapshot',
            'hollywoodbets_identification': {'domain': options['tracked_site']['domain'],
                'default_rank': options['tracked_site']['rank'],
                'default_url': options['tracked_site']['ranking_url']},
            'ours': identity(primary), 'benchmark': identity(competitor),
            'parent_investigation_id': parent_id,
            'status': 'selected_not_analyzed',
            'note': 'Exact observed ranking URLs and positions from one immutable saved SERP snapshot; no search, collector, or model request was started.'}


def _validate_parent(parent_id: str | None, options: dict, primary: dict,
                     competitor: dict) -> None:
    if parent_id is None:
        return
    parent = serp_investigations.read_investigation(parent_id)
    if (parent.get('keyword', '').casefold() != options['keyword'].casefold() or
            parent.get('serp_sha256') != options['snapshot_sha256'] or
            parent.get('ours', {}).get('url') != primary['url']):
        raise ValueError('A competitor branch must preserve the parent keyword, saved SERP, and exact Hollywoodbets page.')
    if normalized_url(parent.get('benchmark', {}).get('url')) == normalized_url(competitor['url']):
        raise ValueError('Choose a different competitor webpage to create a branch.')


def _initialize(investigation_id: str, directory: Path) -> dict:
    selection = serp_investigations.read_investigation(investigation_id)
    if not (directory / 'offline_evidence.json').is_file():
        inventory = investigation_offline.evidence_inventory(selection)
        _atomic_json(directory / 'offline_evidence.json', inventory)
    state = investigation_workflow.get_state(investigation_id)
    evidence_plan = investigation_workflow.collection_plan(investigation_id)
    return {'investigation': selection, 'workflow': state,
            'collection_plan': evidence_plan}


def _persist_selection(investigation_id: str, directory: Path, selection: dict,
                       parent_investigation_id: str | None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    selection_path = directory / 'selection.json'
    if selection_path.is_file():
        saved = json.loads(selection_path.read_text(encoding='utf-8'))
        expected = (selection['keyword'], selection['serp_sha256'], selection['ours']['url'],
                    selection['benchmark']['url'], parent_investigation_id)
        observed = (saved.get('keyword'), saved.get('serp_sha256'), saved.get('ours', {}).get('url'),
                    saved.get('benchmark', {}).get('url'), saved.get('parent_investigation_id'))
        if observed != expected:
            raise ValueError('An investigation already exists with different selection identity.')
    else:
        _atomic_json(selection_path, selection)
    if parent_investigation_id:
        branch_path = directory / 'workflow_branch.json'
        if not branch_path.is_file():
            parent_selection_path = INVESTIGATIONS / parent_investigation_id / 'selection.json'
            parent_meta = {'schema_version': '1.0',
                'parent_investigation_id': parent_investigation_id,
                'parent_selection_sha256': _sha_bytes(parent_selection_path.read_bytes()),
                'created_at': _utc(), 'keyword': selection['keyword'],
                'serp_sha256': selection['serp_sha256'], 'changed_identity': 'benchmark',
                'benchmark_url': selection['benchmark']['url'],
                'compatible_evidence_rechecked': True,
                'note': 'Hollywoodbets and saved SERP are retained; this child comparison selects another exact SERP competitor.'}
            _atomic_json(branch_path, parent_meta)


def create_comparison(*, keyword: str, snapshot_sha256: str, primary_url: str,
                      competitor_url: str, idempotency_key: str,
                      parent_investigation_id: str | None = None) -> dict:
    if not isinstance(idempotency_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', idempotency_key):
        raise ValueError('A valid comparison idempotency key is required.')
    options = selection_options(keyword)
    if options['status'] != 'ready':
        raise ValueError(options.get('message', 'This saved SERP is not ready for comparison.'))
    if not isinstance(snapshot_sha256, str) or snapshot_sha256 != options['snapshot_sha256']:
        raise ValueError('The saved SERP changed since these results were displayed. Reload the snapshot before comparing.')
    primary = next((row for row in options['primary_options'] if row['url'] == primary_url), None)
    if primary is None:
        raise ValueError('Select a Hollywoodbets webpage from the current saved SERP.')
    competitor = next((row for row in options['competitor_options'] if row['url'] == competitor_url), None)
    if competitor is None:
        raise ValueError('Select a valid non-Hollywoodbets competitor webpage from the same saved SERP.')
    if normalized_url(primary['url']) == normalized_url(competitor['url']):
        raise ValueError('Hollywoodbets and competitor webpages must be different.')
    if primary['is_hollywoodbets'] is not True or competitor['is_hollywoodbets'] is not False:
        raise ValueError('The primary page must belong to Hollywoodbets and the competitor page must not.')
    _validate_parent(parent_investigation_id, options, primary, competitor)
    request = {'keyword': options['keyword'], 'snapshot_sha256': options['snapshot_sha256'],
               'primary_url': primary['url'], 'competitor_url': competitor['url'],
               'parent_investigation_id': parent_investigation_id}
    request_fingerprint = _canonical_sha(request)
    request_path = _IDEMPOTENCY_DIR / f'{idempotency_key}.json'

    with _compare_lock():
        if request_path.is_file():
            record = json.loads(request_path.read_text(encoding='utf-8'))
            if record.get('request_fingerprint') != request_fingerprint:
                raise ValueError('This comparison key was already used for a different page selection. Reload and select again.')
            investigation_id = record['investigation_id']
            directory = INVESTIGATIONS / investigation_id
            if record.get('status') == 'creating':
                reserved_selection = _selection_record(investigation_id, options, primary, competitor,
                                                       parent_investigation_id)
                _persist_selection(investigation_id, directory, reserved_selection,
                                   parent_investigation_id)
            result = _initialize(investigation_id, directory)
            saved = result['investigation']
            observed = (saved.get('keyword'), saved.get('serp_sha256'),
                        saved.get('ours', {}).get('url'), saved.get('benchmark', {}).get('url'),
                        saved.get('parent_investigation_id'))
            expected = (request['keyword'], request['snapshot_sha256'], request['primary_url'],
                        request['competitor_url'], request['parent_investigation_id'])
            if observed != expected:
                raise ValueError('The saved comparison record failed its idempotency identity check.')
            if record.get('status') != 'completed':
                record.update(status='completed', completed_at=_utc())
                _atomic_json(request_path, record)
            return {**result, 'idempotent_replay': True, 'created': False}

        investigation_id = uuid.uuid4().hex
        record = {'schema_version': '1.0', 'idempotency_key': idempotency_key,
                  'request_fingerprint': request_fingerprint,
                  'investigation_id': investigation_id, 'status': 'creating',
                  'created_at': _utc()}
        _atomic_json(request_path, record)
        directory = INVESTIGATIONS / investigation_id
        selection = _selection_record(investigation_id, options, primary, competitor,
                                      parent_investigation_id)
        _persist_selection(investigation_id, directory, selection, parent_investigation_id)
        result = _initialize(investigation_id, directory)
        record.update(status='completed', completed_at=_utc())
        _atomic_json(request_path, record)
        return {**result, 'idempotent_replay': False, 'created': True}
