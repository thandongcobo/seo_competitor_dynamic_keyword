"""Investigation-scoped adapters for existing public SEO collector interfaces.

No collector implementation is copied here. Each successful subtask is saved
immediately into an immutable collection version so a later failure/restart can
resume at the first missing item.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from config.settings import ROOT, keyword_slug, settings
from scripts import serp_investigations
from scripts import investigation_offline
from scripts.resolve_pages import normalized_url

COLLECTORS = ('dataforseo', 'playwright', 'lighthouse')
FRESHNESS_DAYS = 30
ADAPTER_VERSION = 'phase1.1.1'
_DATAFORSEO_ACTIONS = {
    'labs_ranked_keywords': '/v3/dataforseo_labs/google/ranked_keywords/live',
    'labs_domain_intersection': '/v3/dataforseo_labs/google/domain_intersection/live',
    'labs_search_intent': '/v3/dataforseo_labs/google/search_intent/live',
    'backlinks_domain_summary': '/v3/backlinks/summary/live',
    'backlinks_page_summary': '/v3/backlinks/summary/live',
}


def evidence_inventory(selection, root=ROOT):
    """Resolve the unchanged inventory callable dynamically for testability."""
    if root == ROOT:
        return investigation_offline.evidence_inventory(selection)
    return investigation_offline.evidence_inventory(selection, root=root)


class CollectionAuthorizationRequired(ValueError):
    def __init__(self, message, plan):
        super().__init__(message)
        self.plan = plan


class CollectionPersistenceError(RuntimeError):
    """A collection record could not be published without risking prior state."""


_COLLECTION_LOCKS_GUARD = threading.Lock()
_COLLECTION_THREAD_LOCKS: dict[str, threading.RLock] = {}
_REPLACE_RETRIES = 12
_REPLACE_RETRY_DELAY_SECONDS = 0.025


def _is_windows_sharing_error(error: OSError) -> bool:
    return os.name == 'nt' and (
        getattr(error, 'winerror', None) in (5, 32, 33) or error.errno in (5, 13)
    )


class _CollectionStateLock:
    """Serialize one investigation's collection writes across threads/processes."""

    def __init__(self, path: Path, timeout: float = 30.0):
        self.path = path
        self.timeout = timeout
        self._thread_lock = None
        self._stream = None
        self._windows = os.name == 'nt'

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        key = str(self.path.resolve())
        with _COLLECTION_LOCKS_GUARD:
            self._thread_lock = _COLLECTION_THREAD_LOCKS.setdefault(key, threading.RLock())
        if not self._thread_lock.acquire(timeout=self.timeout):
            raise CollectionPersistenceError('Timed out waiting for collection-state writer lock.')
        try:
            self._stream = self.path.open('a+b')
            if self._windows:
                import msvcrt
                self._stream.seek(0, os.SEEK_END)
                if self._stream.tell() == 0:
                    self._stream.write(b'0')
                    self._stream.flush()
                deadline = time.monotonic() + self.timeout
                while True:
                    self._stream.seek(0)
                    try:
                        msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise CollectionPersistenceError(
                                'Timed out waiting for cross-process collection-state writer lock.')
                        time.sleep(0.05)
            else:
                import fcntl
                deadline = time.monotonic() + self.timeout
                while True:
                    try:
                        fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise CollectionPersistenceError(
                                'Timed out waiting for cross-process collection-state writer lock.')
                        time.sleep(0.05)
            return self
        except Exception:
            try:
                self._close(unlock=False)
            except OSError:
                pass
            raise

    def _close(self, *, unlock: bool):
        close_error = None
        if self._stream is not None:
            stream, self._stream = self._stream, None
            try:
                if unlock:
                    stream.seek(0)
                    if self._windows:
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                close_error = exc
            finally:
                try:
                    stream.close()
                except OSError as exc:
                    close_error = close_error or exc
        if self._thread_lock is not None:
            self._thread_lock.release()
            self._thread_lock = None
        if close_error:
            raise close_error

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self._close(unlock=True)
        except OSError as exc:
            if exc_type is None:
                raise CollectionPersistenceError(
                    f'Unable to release collection-state writer lock: {exc}') from exc
        return False


def _now():
    return datetime.now(timezone.utc)


def _iso():
    return _now().isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _atomic_json(path: Path, value: dict):
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        temp = Path(temp_name)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(temp, path)
                temp = None
                return
            except PermissionError as exc:
                # Windows reports an open destination as ACCESS_DENIED (5) or
                # SHARING_VIOLATION (32). Retry only these transient cases.
                if not _is_windows_sharing_error(exc) or attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(min(_REPLACE_RETRY_DELAY_SECONDS * (2 ** attempt), 0.1))
    except OSError as exc:
        raise CollectionPersistenceError(f'Unable to atomically persist {path}: {exc}') from exc
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _read(path: Path):
    for attempt in range(_REPLACE_RETRIES):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError as exc:
            if not _is_windows_sharing_error(exc) or attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(min(_REPLACE_RETRY_DELAY_SECONDS * (2 ** attempt), 0.1))


def _base(investigation_id: str) -> Path:
    serp_investigations.read_investigation(investigation_id)
    return serp_investigations.INVESTIGATIONS / investigation_id


def _collection_root(investigation_id: str) -> Path:
    return _base(investigation_id) / 'workflow' / 'collections'


def _active_path(investigation_id: str) -> Path:
    return _base(investigation_id) / 'workflow' / 'collection_active.json'


def _active_manifest(investigation_id: str):
    pointer = _active_path(investigation_id)
    if not pointer.is_file():
        return None, None
    data = _read(pointer)
    version = data.get('version_id')
    if not isinstance(version, str) or not version.isalnum():
        return None, None
    directory = _collection_root(investigation_id) / version
    path = directory / 'manifest.json'
    if not path.is_file():
        return None, None
    manifest = _read(path)
    if manifest.get('investigation_id') != investigation_id or manifest.get('version_id') != version:
        raise ValueError('Collection manifest identity mismatch.')
    return directory, manifest


def _persist_collection_manifest(investigation_id: str, version_dir: Path, manifest: dict) -> None:
    manifest_path = version_dir / 'manifest.json'
    pointer_path = _active_path(investigation_id)
    previous_manifest = None
    try:
        previous_pointer = _read(pointer_path) if pointer_path.is_file() else None
        if (previous_pointer and previous_pointer.get('version_id') == manifest.get('version_id')
                and manifest_path.is_file()):
            previous_manifest = _read(manifest_path)
    except (OSError, ValueError, TypeError):
        previous_manifest = None
    _atomic_json(manifest_path, manifest)
    try:
        _atomic_json(pointer_path, {'version_id': manifest['version_id'],
            'updated_at': _iso(), 'refresh': manifest.get('refresh', False),
            'manifest_sha256': _sha(manifest_path)})
    except CollectionPersistenceError as publish_error:
        # If this version was already active, restore its last published manifest
        # so the unchanged pointer's hash continues to describe the same state.
        if previous_manifest is not None:
            try:
                _atomic_json(manifest_path, previous_manifest)
            except CollectionPersistenceError as rollback_error:
                raise CollectionPersistenceError(
                    f'{publish_error}; restoring the previous collection manifest also failed: '
                    f'{rollback_error}') from publish_error
        raise


def _safe_error_message(error: Exception) -> str:
    message = str(error)[:1000]
    for secret in (settings.dataforseo_login, settings.dataforseo_password):
        if secret:
            message = message.replace(secret, '[REDACTED]')
    message = re.sub(r'(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+', r'\1[REDACTED]', message)
    message = re.sub(r'(?i)(password|api[_-]?key|token)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', message)
    return message


def _charge_value(value):
    try:
        result = float(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _collection_attempt_event(investigation_id: str, version_dir: Path, manifest: dict,
                              item_key: str, attempt_id: str, event: dict) -> None:
    entry = (manifest.get('items') or {}).get(item_key) or {}
    attempts = entry.setdefault('attempts', [])
    attempt = next((row for row in reversed(attempts) if row.get('attempt_id') == attempt_id), None)
    if attempt is None:
        return
    event_type = event.get('event')
    if event_type == 'transmission_started':
        attempt['transmission_started_at'] = _iso()
        attempt['transmission_status'] = 'in_progress'
        manifest['statistics']['dataforseo_transmission_attempts'] = (
            manifest['statistics'].get('dataforseo_transmission_attempts', 0) + 1)
    elif event_type == 'transmission_outcome_unknown':
        attempt['transmission_status'] = 'unknown'
        manifest['statistics']['dataforseo_transmission_outcome_unknown'] = (
            manifest['statistics'].get('dataforseo_transmission_outcome_unknown', 0) + 1)
    elif event_type == 'http_response':
        attempt['transmission_status'] = 'confirmed'
        attempt['http_status'] = event.get('http_status')
        manifest['statistics']['dataforseo_http_responses_received'] = (
            manifest['statistics'].get('dataforseo_http_responses_received', 0) + 1)
    elif event_type == 'api_response':
        attempt['api_status'] = event.get('api_status')
        charge = _charge_value(event.get('reported_cost_usd'))
        if charge is not None and attempt.get('api_reported_charge_usd') is None:
            attempt['api_reported_charge_usd'] = charge
            manifest['statistics']['api_confirmed_charges_usd'] = (
                manifest['statistics'].get('api_confirmed_charges_usd', 0.0) + charge)
            manifest['statistics']['api_confirmed_charge_records'] = (
                manifest['statistics'].get('api_confirmed_charge_records', 0) + 1)
    _persist_collection_manifest(investigation_id, version_dir, manifest)


def collection_status(investigation_id: str) -> dict:
    """Read the active collection manifest without planning or starting work."""
    selection = serp_investigations.read_investigation(investigation_id)
    version_dir, manifest = _active_manifest(investigation_id)
    selected = set((manifest or {}).get('collector_selection') or [])
    entries = (manifest or {}).get('items') or {}
    rows = []
    for item in _items(selection):
        entry = entries.get(item['key']) or {}
        raw_status = str(entry.get('status') or '').lower()
        cache_status = entry.get('cache_status')
        if raw_status == 'completed':
            status = ('reused' if cache_status in (
                'original_investigation_inventory', 'compatible_investigation_version',
                'this_investigation_collection_version', 'existing_dataforseo_request_cache',
                'saved_evidence') else 'completed')
        elif raw_status in ('running', 'processing', 'failed', 'skipped', 'pending'):
            status = raw_status
        elif manifest and selected and item['collector'] not in selected:
            status = 'skipped'
        else:
            status = 'pending'
        attempts = entry.get('attempts') if isinstance(entry.get('attempts'), list) else []
        attempt_count = len(attempts)
        if not attempt_count and entry.get('attempt_id'):
            attempt_count = 1
        first_attempt = attempts[0] if attempts else {}
        latest_attempt = attempts[-1] if attempts else {}
        rows.append({
            'key': item['key'], 'collector': item['collector'], 'evidence_type': item['kind'],
            'status': status, 'attempt_count': attempt_count,
            'started_at': entry.get('started_at') or first_attempt.get('started_at'),
            'completed_at': entry.get('completed_at') or entry.get('finished_at') or latest_attempt.get('finished_at'),
            'error': (_safe_error_message(RuntimeError(entry.get('message')))
                      if entry.get('message') else None),
            'diagnostic_reference': entry.get('diagnostic_reference') or latest_attempt.get('diagnostic_reference'),
            'http_status': entry.get('http_status') or latest_attempt.get('http_status'),
            'api_status': entry.get('api_status') or latest_attempt.get('api_status'),
            'transmission_status': entry.get('transmission_status') or latest_attempt.get('transmission_status'),
        })
    counts = {key: sum(row['status'] == key for row in rows)
              for key in ('completed', 'reused', 'failed', 'pending', 'running', 'processing', 'skipped')}
    statistics = (manifest or {}).get('statistics', {})
    return {'schema_version': '1.0', 'investigation_id': investigation_id,
        'version_id': (manifest or {}).get('version_id'),
        'status': (manifest or {}).get('status', 'not_started'),
        'updated_at': _read(_active_path(investigation_id)).get('updated_at') if _active_path(investigation_id).is_file() else None,
        'summary': {'required': len(rows), **counts}, 'items': rows,
        'statistics': statistics,
        'request_accounting': {
            'operation_attempts': statistics.get('operation_attempts', 0),
            'dataforseo_transmission_attempts': statistics.get('dataforseo_transmission_attempts', 0),
            'dataforseo_http_responses_received': statistics.get('dataforseo_http_responses_received', 0),
            'dataforseo_transmission_outcome_unknown': statistics.get('dataforseo_transmission_outcome_unknown', 0),
            'api_confirmed_charges_usd': statistics.get('api_confirmed_charges_usd', 0.0),
            'api_confirmed_charge_records': statistics.get('api_confirmed_charge_records', 0),
            'legacy_paid_requests_made': statistics.get('paid_requests_made', 0),
            'legacy_counter_note': 'Compatibility count of successful DataForSEO evidence saves; it is not a transmission count or proof of charges.'}}


def _safe_configuration(collector: str, keyword: str, device='mobile') -> dict:
    base = {'adapter_version': ADAPTER_VERSION, 'keyword': keyword,
            'language_code': settings.language_code}
    if collector == 'dataforseo':
        return {**base, 'labs_location_name': settings.labs_location_name,
                'api_family': 'DataForSEO v3'}
    if collector == 'playwright':
        return {**base, 'location_coordinate': settings.location_coordinate,
                'navigation_timeout_ms': settings.playwright_navigation_timeout_ms,
                'render_timeout_seconds': settings.playwright_render_timeout_seconds,
                'public_only': True,
                'browser_identity_sha256': hashlib.sha256(settings.playwright_browser_path.encode()).hexdigest()}
    return {**base, 'device': device,
            'categories': ['performance', 'accessibility', 'best-practices', 'seo'],
            'chrome_flags': '--headless=new --disable-gpu'}


def _items(selection: dict) -> list[dict]:
    keyword = selection['keyword']
    slug = keyword_slug(keyword)
    rows = []
    for side in ('ours', 'benchmark'):
        identity = selection[side]
        rows.append({'key': f'labs_ranked_keywords:{side}', 'kind': 'labs_ranked_keywords',
                     'side': side, 'collector': 'dataforseo', 'scope': 'domain',
                     'target': identity['domain']})
        rows.extend([
            {'key': f'backlinks_domain_summary:{side}', 'kind': 'backlinks_domain_summary',
             'side': side, 'collector': 'dataforseo', 'scope': 'domain', 'target': identity['domain']},
            {'key': f'backlinks_page_summary:{side}', 'kind': 'backlinks_page_summary',
             'side': side, 'collector': 'dataforseo', 'scope': 'page', 'target': identity['url']},
            {'key': f'playwright_page:{side}', 'kind': 'playwright_page', 'side': side,
             'collector': 'playwright', 'scope': 'page', 'target': identity['url']},
            {'key': f'lighthouse_mobile:{side}', 'kind': 'lighthouse_mobile', 'side': side,
             'collector': 'lighthouse', 'scope': 'page', 'device': 'mobile', 'target': identity['url']},
        ])
    rows.extend([
        {'key': 'labs_domain_intersection:shared', 'kind': 'labs_domain_intersection',
         'side': None, 'collector': 'dataforseo', 'scope': 'domain_pair',
         'target': [selection['ours']['domain'], selection['benchmark']['domain']]},
        {'key': 'labs_search_intent:shared', 'kind': 'labs_search_intent',
         'side': None, 'collector': 'dataforseo', 'scope': 'keyword', 'target': keyword},
    ])
    for row in rows:
        config = _safe_configuration(row['collector'], keyword, row.get('device', 'mobile'))
        row['keyword'] = keyword
        row['investigation_id'] = selection['investigation_id']
        row['configuration'] = config
        endpoint, payload = _dataforseo_request(row, selection) if row['collector'] == 'dataforseo' else (None, None)
        row['endpoint'] = endpoint
        row['payload'] = payload
        row['request_fingerprint'] = _request_fingerprint(endpoint, payload) if endpoint else None
        row['context_fingerprint'] = _digest({'identity': row['target'], 'scope': row['scope'],
            'keyword': keyword if row['kind'] in ('labs_search_intent', 'labs_domain_intersection') else None,
            'configuration': config, 'endpoint': endpoint, 'payload': payload})
    return rows


def _dataforseo_request(item: dict, selection: dict):
    from collectors.labs_collector import (ranked_keywords_payload, domain_intersection_payload,
                                           search_intent_payload)
    from collectors.backlinks_collector import summary_payload
    kind, target = item['kind'], item['target']
    if kind == 'labs_ranked_keywords':
        endpoint = _DATAFORSEO_ACTIONS[kind]
        payload = ranked_keywords_payload(target, settings.labs_location_name, settings.language_code, 100)
    elif kind == 'labs_domain_intersection':
        endpoint = _DATAFORSEO_ACTIONS[kind]
        payload = domain_intersection_payload(selection['ours']['domain'], selection['benchmark']['domain'],
            settings.labs_location_name, settings.language_code, 100, keyword=selection['keyword'])
    elif kind == 'labs_search_intent':
        endpoint = _DATAFORSEO_ACTIONS[kind]
        payload = search_intent_payload(selection['keyword'])
    elif kind.startswith('backlinks_'):
        endpoint = _DATAFORSEO_ACTIONS[kind]
        payload = summary_payload(target, include_subdomains=(item['scope'] == 'domain'))
    else:
        raise ValueError(f'No DataForSEO adapter for {kind}.')
    return endpoint, payload


def _request_fingerprint(endpoint, payload) -> str:
    from collectors.request_cache import request_fingerprint
    return request_fingerprint('POST', endpoint, payload)


def _api_success(response) -> bool:
    return bool(isinstance(response, dict) and response.get('status_code') == 20000 and
                any(isinstance(task, dict) and task.get('status_code') == 20000
                    for task in response.get('tasks', [])))


def _response_matches(item: dict, response: dict, metadata: dict | None = None) -> bool:
    if not _api_success(response):
        return False
    tasks = [task for task in response.get('tasks', []) if isinstance(task, dict)]
    if item['kind'] == 'labs_ranked_keywords':
        return any((task.get('data') or {}).get('target', '').lower().removeprefix('www.') == item['target']
                   for task in tasks)
    if item['kind'].startswith('backlinks_'):
        if not metadata:
            return False
        target = metadata.get('target')
        target_ok = (normalized_url(target) == normalized_url(item['target']) if item['scope'] == 'page'
                     else str(target).lower().removeprefix('www.') == item['target'])
        return (metadata.get('keyword') == item['keyword'] and metadata.get('scope') == item['scope']
                and target_ok and metadata.get('endpoint') in (None, item['endpoint']))
    if item['kind'] == 'labs_domain_intersection':
        domains = set(item['target'])
        return any({(task.get('data') or {}).get('target1'), (task.get('data') or {}).get('target2')} == domains
                   for task in tasks)
    if item['kind'] == 'labs_search_intent':
        return any(item['keyword'].casefold() in [str(x).casefold() for x in
                   (task.get('data') or {}).get('keywords', [])] for task in tasks)
    return False


def _page_matches(item: dict, data: dict) -> bool:
    return bool(isinstance(data, dict) and data.get('keyword') == item['keyword'] and
        normalized_url(data.get('requested_url')) == normalized_url(item['target']) and
        normalized_url(data.get('ranking_url') or data.get('requested_url')) == normalized_url(item['target']) and
        data.get('extraction_status') == 'complete' and not data.get('crawl_failed') and
        not data.get('blocked') and normalized_url(data.get('final_url')))


def _lighthouse_matches(item: dict, data: dict) -> bool:
    return bool(isinstance(data, dict) and data.get('lighthouseVersion') and
                normalized_url(data.get('requestedUrl')) == normalized_url(item['target']))


def _artifact_compatible(item: dict, raw: dict, metadata: dict | None, *, strict_context=True) -> bool:
    if item['collector'] == 'dataforseo':
        if strict_context and metadata:
            if (metadata.get('configuration_verified') is False or
                    metadata.get('context_fingerprint') != item['context_fingerprint'] or
                    metadata.get('configuration') != item['configuration']):
                return False
        if item['kind'].startswith('backlinks_'):
            return _response_matches(item, raw, metadata)
        return _response_matches(item, raw)
    if metadata:
        raw_ok = (_page_matches(item, raw) if item['kind'] == 'playwright_page'
                  else _lighthouse_matches(item, raw) if item['kind'] == 'lighthouse_mobile' else False)
        return (raw_ok and (metadata.get('configuration_verified') is not False or not strict_context) and
                metadata.get('context_fingerprint') == item['context_fingerprint'] and
                metadata.get('keyword') == item['keyword'] and
                metadata.get('target') == item['target'] and
                metadata.get('scope') == item['scope'] and
                metadata.get('configuration') == item['configuration'] and
                (not strict_context or _fresh(metadata.get('captured_at'))))
    if strict_context:
        return False
    return _page_matches(item, raw) if item['kind'] == 'playwright_page' else _lighthouse_matches(item, raw)


def _fresh(value) -> bool:
    try:
        timestamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        age = _now() - timestamp
        return timedelta(0) <= age <= timedelta(days=FRESHNESS_DAYS)
    except (TypeError, ValueError):
        return False


def _load_item_file(item: dict, raw_path: Path, metadata_path: Path | None = None,
                    *, strict_context=True, same_investigation=False):
    try:
        raw = _read(raw_path)
        metadata = _read(metadata_path) if metadata_path and metadata_path.is_file() else None
        if not _artifact_compatible(item, raw, metadata, strict_context=strict_context):
            # An exact current-investigation historical inventory may have no
            # adapter sidecar; verify its inventory hash before trusting it.
            if not same_investigation or metadata is not None:
                return None
            if item['kind'] == 'playwright_page' and not _page_matches(item, raw):
                return None
            if item['kind'] == 'lighthouse_mobile' and not _lighthouse_matches(item, raw):
                return None
            if item['collector'] == 'dataforseo' and not _response_matches(item, raw, metadata):
                return None
        return {'raw': raw, 'metadata': metadata, 'raw_path': raw_path,
                'metadata_path': metadata_path if metadata_path and metadata_path.is_file() else None,
                'sha256': _sha(raw_path), 'metadata_sha256': _sha(metadata_path) if metadata_path and metadata_path.is_file() else None}
    except (OSError, ValueError, TypeError):
        return None


def _current_inventory(selection: dict, investigation_id: str) -> dict:
    base = _base(investigation_id)
    saved_path = base / 'offline_evidence.json'
    try:
        saved = _read(saved_path)
    except (OSError, ValueError):
        saved = None
    existing = evidence_inventory(selection)
    # Prefer a hash-pinned original inventory record for this investigation.
    if isinstance(saved, dict) and saved.get('investigation_id') == investigation_id:
        for entry in saved.get('entries', []):
            if entry.get('status') != 'available' or not entry.get('path'):
                continue
            path = ROOT / entry['path']
            if path.is_file() and _sha(path) == entry.get('sha256'):
                match = next((row for row in existing.get('entries', [])
                              if row.get('kind') == entry.get('kind') and row.get('side') == entry.get('side')),
                             None)
                if match and match.get('status') != 'available':
                    existing['entries'].remove(match)
                    existing['entries'].append(entry)
    return existing


def _source_saved_inventory(item: dict, inventory: dict, investigation_id: str):
    base = _base(investigation_id)
    is_branch = (base / 'workflow_branch.json').is_file()
    try:
        pinned = _read(base / 'offline_evidence.json')
    except (OSError, ValueError):
        pinned = {}
    if pinned.get('investigation_id') != investigation_id:
        return None
    # Only an inventory captured in this investigation binds legacy, sidecar-
    # free artifacts to its original exact page identities.
    for entry in pinned.get('entries', []):
        if entry.get('status') != 'available' or (entry.get('kind'), entry.get('side')) != (item['kind'], item['side']):
            continue
        path = ROOT / entry.get('path', '')
        if not path.is_file() or _sha(path) != entry.get('sha256'):
            continue
        if is_branch:
            # A branch is a new evidence context. Legacy files without a
            # configuration sidecar cannot prove that context; reuse only
            # adapter-provenanced parent items in _cross_investigation_reuse.
            continue
        meta_path = path.with_suffix('.meta.json') if item['kind'].startswith('backlinks_') else None
        candidate = _load_item_file(item, path, meta_path, strict_context=False, same_investigation=True)
        if candidate:
            candidate.update(reuse_source='original_investigation_inventory', age_policy='historical_reopen')
            return candidate
    # Cross-investigation legacy files have no reliable collector config; do
    # not reuse them. New adapter-provenanced versions are considered below.
    return None


def _iter_manifests(exclude_id: str):
    root = serp_investigations.INVESTIGATIONS
    if not root.is_dir():
        return
    for manifest_path in root.glob('*/workflow/collections/*/manifest.json'):
        try:
            manifest = _read(manifest_path)
            if manifest.get('investigation_id') != exclude_id:
                yield manifest_path.parent, manifest
        except (OSError, ValueError, TypeError):
            continue


def _cross_investigation_reuse(item: dict, investigation_id: str):
    for version_dir, manifest in _iter_manifests(investigation_id):
        entry = (manifest.get('items') or {}).get(item['key'])
        if not entry or entry.get('status') != 'completed' or not _fresh(entry.get('captured_at')):
            continue
        if entry.get('context_fingerprint') != item['context_fingerprint']:
            continue
        raw_path = version_dir / entry.get('raw_file', '')
        meta_path = version_dir / entry.get('metadata_file', '') if entry.get('metadata_file') else None
        if not raw_path.is_file() or _sha(raw_path) != entry.get('sha256'):
            continue
        candidate = _load_item_file(item, raw_path, meta_path, strict_context=True)
        if candidate and candidate.get('sha256') == entry.get('sha256'):
            candidate.update(reuse_source='compatible_investigation_version', age_policy=f'{FRESHNESS_DAYS}_day_cross_investigation')
            return candidate
    return None


def _request_cache_candidate(item: dict):
    if item['collector'] != 'dataforseo':
        return None
    from collectors.request_cache import cache_path
    path = cache_path('POST', item['endpoint'], item['payload'])
    if not path.is_file():
        return None
    try:
        entry = _read(path)
        if (entry.get('method') != 'POST' or entry.get('path') != item['endpoint'] or
                entry.get('payload') != item['payload'] or not _fresh(entry.get('cached_at_utc')) or
                not _response_matches(item, entry.get('response'), _metadata_for_request_cache(item))):
            return None
        return {'raw': entry['response'], 'metadata': _metadata_for_request_cache(item),
                'raw_path': None, 'metadata_path': None, 'sha256': _digest(entry['response']),
                'request_cache_path': path, 'reuse_source': 'existing_dataforseo_request_cache',
                'age_policy': f'{FRESHNESS_DAYS}_day_request_cache'}
    except (OSError, ValueError, TypeError):
        return None


def _metadata_for_request_cache(item):
    return {'keyword': item['keyword'], 'scope': item['scope'], 'target': item['target'],
            'endpoint': item['endpoint']}


def _current_version_item(item: dict, version_dir: Path | None, manifest: dict | None):
    if not version_dir or not manifest:
        return None
    row = (manifest.get('items') or {}).get(item['key'])
    if not row or row.get('status') != 'completed' or row.get('context_fingerprint') != item['context_fingerprint']:
        return None
    raw_path = version_dir / row.get('raw_file', '')
    meta_path = version_dir / row.get('metadata_file', '') if row.get('metadata_file') else None
    if not raw_path.is_file() or _sha(raw_path) != row.get('sha256'):
        return None
    candidate = _load_item_file(item, raw_path, meta_path, strict_context=False, same_investigation=True)
    if candidate:
        candidate.update(reuse_source='this_investigation_collection_version', age_policy='historical_reopen')
        return candidate
    return None


def _item_plan(item: dict, investigation_id: str, inventory: dict, version_dir, manifest,
               *, refresh=False, selected=COLLECTORS):
    force = refresh and item['collector'] in selected
    if not force:
        candidate = _current_version_item(item, version_dir, manifest)
        if candidate:
            return {'item': item, 'status': 'available', 'reuse_source': candidate['reuse_source'],
                    'candidate': candidate, 'requests': 0}
        candidate = _source_saved_inventory(item, inventory, investigation_id)
        if candidate:
            return {'item': item, 'status': 'available', 'reuse_source': candidate['reuse_source'],
                    'candidate': candidate, 'requests': 0}
        candidate = _cross_investigation_reuse(item, investigation_id)
        if candidate:
            return {'item': item, 'status': 'available', 'reuse_source': candidate['reuse_source'],
                    'candidate': candidate, 'requests': 0}
        candidate = _request_cache_candidate(item)
        if candidate:
            return {'item': item, 'status': 'cached', 'reuse_source': candidate['reuse_source'],
                    'candidate': candidate, 'requests': 0}
    if item['collector'] not in selected:
        return {'item': item, 'status': 'missing', 'reuse_source': None, 'candidate': None, 'requests': 0}
    return {'item': item, 'status': 'refresh_required' if force else 'missing',
            'reuse_source': None, 'candidate': None,
            'requests': 1 if item['collector'] == 'dataforseo' else 0,
            'external_operations': 1 if item['collector'] in ('playwright', 'lighthouse') else 0}


def plan_collection(investigation_id: str, *, collectors=None, refresh=False) -> dict:
    selection = serp_investigations.read_investigation(investigation_id)
    selected = tuple(COLLECTORS if collectors is None else dict.fromkeys(collectors))
    if any(value not in COLLECTORS for value in selected):
        raise ValueError('Unknown collector category.')
    if type(refresh) is not bool:
        raise ValueError('refresh must be boolean.')
    inventory = _current_inventory(selection, investigation_id)
    version_dir, manifest = _active_manifest(investigation_id)
    plans = [_item_plan(item, investigation_id, inventory, version_dir, manifest,
                        refresh=refresh, selected=selected) for item in _items(selection)]
    dataforseo_new = sum(row['requests'] for row in plans)
    result = {
        'schema_version': '1.1', 'investigation_id': investigation_id,
        'keyword': selection['keyword'], 'refresh': refresh,
        'collector_selection': list(selected), 'items': [],
        'summary': {'required_items': len(plans),
                    'available_or_reusable': sum(row['status'] == 'available' for row in plans),
                    'request_cache_hits': sum(row['status'] == 'cached' for row in plans),
                    'missing_items': sum(row['status'] in ('missing', 'refresh_required') for row in plans),
                    'dataforseo_paid_requests': dataforseo_new,
                    'playwright_top_level_captures': sum(row.get('external_operations', 0)
                                                         for row in plans if row['item']['collector'] == 'playwright'),
                    'lighthouse_runs': sum(row.get('external_operations', 0)
                                           for row in plans if row['item']['collector'] == 'lighthouse'),
                    'estimated_cost_usd': None,
                    'cost_note': 'DataForSEO charges depend on endpoint/account pricing; no monetary estimate is available before response.'},
        '_plans': plans,
    }
    for row in plans:
        item = row['item']
        result['items'].append({'key': item['key'], 'kind': item['kind'], 'side': item['side'],
            'collector': item['collector'], 'scope': item['scope'], 'device': item.get('device'),
            'target': item['target'], 'status': row['status'], 'reuse_source': row['reuse_source'],
            'configuration_fingerprint': item['context_fingerprint'],
            'request_fingerprint': item['request_fingerprint'], 'external_requests_if_run': row.get('requests', 0),
            'external_operations_if_run': row.get('external_operations', 0)})
    result['ready'] = result['summary']['missing_items'] == 0
    return result


def _collection_version(investigation_id, refresh):
    version_dir, manifest = _active_manifest(investigation_id)
    if not refresh and version_dir and manifest:
        return version_dir, manifest
    version_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + uuid.uuid4().hex[:8]
    version_dir = _collection_root(investigation_id) / version_id
    manifest = {'schema_version': '1.1', 'investigation_id': investigation_id,
        'version_id': version_id, 'status': 'running', 'started_at': _iso(),
        'completed_at': None, 'keyword': serp_investigations.read_investigation(investigation_id)['keyword'],
        'items': {}, 'attempts': [], 'failures': [], 'statistics': {
            'evidence_reuse_hits': 0, 'request_cache_hits': 0, 'cache_misses': 0,
            'paid_requests_made': 0, 'playwright_top_level_captures': 0,
            'lighthouse_runs': 0, 'reported_cost_usd': 0.0,
            'operation_attempts': 0, 'dataforseo_transmission_attempts': 0,
            'dataforseo_http_responses_received': 0,
            'dataforseo_transmission_outcome_unknown': 0,
            'api_confirmed_charges_usd': 0.0, 'api_confirmed_charge_records': 0}}
    version_dir.mkdir(parents=True, exist_ok=False)
    _persist_collection_manifest(investigation_id, version_dir, manifest)
    return version_dir, manifest


def _store_artifact(version_dir: Path, item: dict, raw: dict, *, metadata: dict,
                    source_path: Path | None = None, source_meta: Path | None = None):
    evidence_dir = version_dir / 'evidence'
    evidence_dir.mkdir(parents=True, exist_ok=True)
    file_id = hashlib.sha256(item['key'].encode()).hexdigest()[:16]
    raw_rel = Path('evidence') / f'{file_id}.json'
    meta_rel = Path('evidence') / f'{file_id}.meta.json'
    raw_path, meta_path = version_dir / raw_rel, version_dir / meta_rel
    if source_path:
        shutil.copy2(source_path, raw_path)
        _atomic_json(meta_path, metadata)
    else:
        _atomic_json(raw_path, raw)
        _atomic_json(meta_path, metadata)
    metadata_written = _read(meta_path)
    if not _artifact_compatible(item, _read(raw_path), metadata_written,
                                strict_context=metadata_written.get('configuration_verified') is not False):
        raise ValueError(f'Collector output failed identity or configuration verification for {item["key"]}.')
    return {'status': 'completed', 'kind': item['kind'], 'side': item['side'],
            'collector': item['collector'], 'scope': item['scope'], 'target': item['target'],
            'keyword': item['keyword'], 'configuration': item['configuration'],
            'context_fingerprint': item['context_fingerprint'],
            'request_fingerprint': item['request_fingerprint'],
            'endpoint': item.get('endpoint'), 'captured_at': metadata['captured_at'],
            'request_metadata': ({'method': 'POST', 'endpoint': item['endpoint'], 'payload': item['payload']}
                                 if item['collector'] == 'dataforseo' else
                                 {'operation': 'crawl_page'} if item['collector'] == 'playwright' else
                                 {'operation': 'lighthouse', 'device': item.get('device')}),
            'raw_file': raw_rel.as_posix(), 'metadata_file': meta_rel.as_posix(),
            'sha256': _sha(raw_path), 'metadata_sha256': _sha(meta_path),
            'reported_cost_usd': metadata.get('reported_cost_usd'),
            'cache_status': metadata.get('cache_status'),
            'final_url': metadata.get('final_url')}


def _save_item(version_dir, manifest, item, raw, *, cache_status, paid=False,
               external_operation=False, source_path=None, source_meta=None,
               reported_cost=None, attempt_id=None):
    now = _iso()
    source_metadata = {}
    if source_path and source_meta and source_meta.is_file():
        try:
            source_metadata = _read(source_meta)
        except (OSError, ValueError):
            source_metadata = {}
    configuration_verified = bool(source_path and source_metadata.get('context_fingerprint') == item['context_fingerprint']
                                   and source_metadata.get('configuration') == item['configuration']) if source_path else True
    captured_at = _iso()
    if source_path:
        stamp = source_metadata.get('captured_at')
        if not stamp:
            stamp = datetime.fromtimestamp(source_path.stat().st_mtime, timezone.utc).isoformat()
        captured_at = stamp
    metadata = {'schema_version': '1.1', 'investigation_id': manifest['investigation_id'],
        'version_id': manifest['version_id'], 'item_key': item['key'], 'kind': item['kind'],
        'side': item['side'], 'scope': item['scope'], 'target': item['target'],
        'keyword': item['keyword'], 'configuration': item['configuration'],
        'context_fingerprint': item['context_fingerprint'],
        'request_fingerprint': item['request_fingerprint'], 'endpoint': item.get('endpoint'),
        'captured_at': captured_at, 'configuration_verified': configuration_verified,
        'cache_status': cache_status,
        'reported_cost_usd': reported_cost, 'credentials_stored': False,
        'source_metadata_sha256': _sha(source_meta) if source_meta and source_meta.is_file() else None,
        'final_url': (raw.get('final_url') if item['kind'] == 'playwright_page' else
                      raw.get('finalDisplayedUrl') if item['kind'] == 'lighthouse_mobile' else None)}
    row = _store_artifact(version_dir, item, raw, metadata=metadata,
                          source_path=source_path, source_meta=source_meta)
    row['captured_at'] = metadata['captured_at']
    row['configuration_verified'] = metadata['configuration_verified']
    row['attempt_id'] = attempt_id
    row['status'] = 'completed'
    previous = (manifest.get('items') or {}).get(item['key']) or {}
    row['attempts'] = previous.get('attempts', [])
    row['attempt_count'] = len(row['attempts'])
    row['started_at'] = previous.get('started_at')
    row['completed_at'] = now
    row['http_status'] = previous.get('http_status')
    row['api_status'] = previous.get('api_status')
    row['transmission_status'] = previous.get('transmission_status')
    row['message'] = None
    manifest['items'][item['key']] = row
    stats = manifest['statistics']
    if cache_status in ('original_investigation_inventory', 'compatible_investigation_version', 'this_investigation_collection_version'):
        stats['evidence_reuse_hits'] += 1
    elif cache_status == 'existing_dataforseo_request_cache':
        stats['request_cache_hits'] += 1
    else:
        stats['cache_misses'] += 1
    if paid:
        stats['paid_requests_made'] += 1
    if item['collector'] == 'playwright' and external_operation:
        stats['playwright_top_level_captures'] += 1
    if item['collector'] == 'lighthouse' and external_operation:
        stats['lighthouse_runs'] += 1
    if paid and reported_cost is not None:
        try:
            stats['reported_cost_usd'] += float(reported_cost)
        except (ValueError, TypeError):
            pass
    if paid and reported_cost is not None:
        attempts = row.get('attempts') or []
        last_attempt = attempts[-1] if attempts else {}
        if last_attempt.get('api_reported_charge_usd') is None:
            charge = _charge_value(reported_cost)
            if charge is not None:
                stats['api_confirmed_charges_usd'] = stats.get('api_confirmed_charges_usd', 0.0) + charge
                stats['api_confirmed_charge_records'] = stats.get('api_confirmed_charge_records', 0) + 1
                last_attempt['api_reported_charge_usd'] = charge
    _persist_collection_manifest(manifest['investigation_id'], version_dir, manifest)
    return row


def _run_dataforseo(item, executor=None, *, event_callback=None):
    if executor:
        response = executor(item)
    else:
        from collectors.dataforseo_client import DataForSEOClient
        response = DataForSEOClient(event_callback=event_callback).post(item['endpoint'], item['payload'])
    if not _response_matches(item, response, _metadata_for_request_cache(item)):
        raise ValueError('DataForSEO response failed status/target/scope validation.')
    return response, response.get('cost')


def _run_playwright(item, executor=None):
    if executor:
        result = executor(item)
    else:
        from collectors.playwright_collector import crawl_page
        directory = (_base(item['investigation_id']) / 'workflow' / 'collections' / 'captures' /
                     f'{item["side"]}_{uuid.uuid4().hex}')
        result = crawl_page(item['target'], artifact_dir=directory, public_only=True)
    if not isinstance(result, dict):
        raise ValueError('Playwright collector returned a non-object result.')
    captured = dict(result)
    captured.update({'keyword': item['keyword'], 'ranking_url': item['target'],
                     'target_side': item['side'], 'evidence_scope': 'page',
                     'url_alignment': 'matched' if normalized_url(result.get('final_url')) == normalized_url(item['target'])
                                      else 'redirected_from_selected_url'})
    if not _page_matches(item, captured):
        if captured.get('blocked') or captured.get('extraction_status') == 'blocked':
            message = 'Playwright capture blocked or sign-in required.'
        elif captured.get('extraction_status') != 'complete' or captured.get('crawl_failed'):
            reason = captured.get('content_quality_reason') or captured.get('extraction_status') or 'main_content_not_confirmed'
            message = f'Playwright capture incomplete: {str(reason)[:240]}.'
        else:
            message = 'Playwright result failed requested URL identity validation.'
        error = ValueError(message)
        error.diagnostic_reference = captured.get('diagnostic_reference')
        error.safe_message = message
        raise error
    return captured, None


def _run_lighthouse(item, executor=None):
    if executor:
        result = executor(item)
    else:
        from scripts.collect_lighthouse import build_command
        import tempfile
        npx = shutil.which('npx') or shutil.which('npx.cmd') or 'npx'
        temp = _base(item['investigation_id']) / 'workflow' / 'collections' / 'pending' / f'{uuid.uuid4().hex}.json'
        temp.parent.mkdir(parents=True, exist_ok=True)
        command = build_command(item['target'], temp, device=item.get('device', 'mobile'), npx=npx)
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=300,
                                       check=False, errors='replace')
            if completed.returncode != 0:
                raise RuntimeError(f'Lighthouse failed with exit code {completed.returncode}.')
            result = _read(temp)
        finally:
            temp.unlink(missing_ok=True)
            try:
                temp.parent.rmdir()
            except OSError:
                pass
    if not _lighthouse_matches(item, result):
        raise ValueError('Lighthouse output is invalid or belongs to a different requested URL.')
    return result, None


def _overlay_filename(item: dict, slug: str) -> Path:
    if item['kind'] == 'labs_ranked_keywords':
        return Path('labs') / f'{slug}_ranked_{item["side"]}_phase11.json'
    if item['kind'].startswith('backlinks_'):
        scope = item['scope']
        return Path('backlinks') / f'{slug}_{item["side"]}_{scope}_summary.json'
    if item['kind'] == 'playwright_page':
        return Path('pages') / f'{slug}_google_{item["side"]}.json'
    if item['kind'] == 'lighthouse_mobile':
        return Path('lighthouse') / f'{slug}_google_{item["side"]}_mobile.json'
    if item['kind'] == 'labs_domain_intersection':
        return Path('labs') / f'{slug}_domain_intersection.json'
    if item['kind'] == 'labs_search_intent':
        return Path('labs') / f'{slug}_search_intent.json'
    raise ValueError(f'Unsupported evidence overlay item: {item["kind"]}')


def _build_overlay(investigation_id: str, selection: dict, version_dir: Path, manifest: dict):
    overlay = version_dir / 'root'
    marker = overlay / 'phase1_1_overlay.json'
    if marker.is_file():
        record = _read(marker)
        if record.get('manifest_sha256') == _sha(version_dir / 'manifest.json'):
            return overlay, record
        raise ValueError('The active evidence overlay is immutable; create a new collection version.')
    slug = keyword_slug(selection['keyword'])
    for item in _items(selection):
        row = (manifest.get('items') or {}).get(item['key'])
        if not row or row.get('status') != 'completed':
            raise ValueError('Cannot build evidence overlay while a required item is missing: ' + item['key'])
        source = version_dir / row['raw_file']
        if not source.is_file() or _sha(source) != row.get('sha256'):
            raise ValueError('A collection artifact failed its checksum: ' + item['key'])
        target = overlay / 'data' / 'raw' / _overlay_filename(item, slug)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if item['kind'].startswith('backlinks_'):
            metadata = _read(version_dir / row['metadata_file'])
            _atomic_json(target.with_suffix('.meta.json'), {
                'keyword': selection['keyword'], 'side': item['side'], 'scope': item['scope'],
                'engine': 'google' if item['scope'] == 'page' else None,
                'target': item['target'], 'endpoint': item['endpoint'],
                'configuration_fingerprint': item['context_fingerprint'],
                'collection_version': manifest['version_id'], 'captured_at': metadata['captured_at']})
    serp_src = ROOT / 'data' / 'processed' / slug / 'serp_google.json'
    if not serp_src.is_file():
        raise ValueError('The saved normalized Google SERP is unavailable; no overlay was published.')
    serp = _read(serp_src)
    if serp.get('keyword', '').casefold() != selection['keyword'].casefold():
        raise ValueError('The saved SERP keyword does not match the investigation.')
    processed_serp = overlay / 'data' / 'processed' / slug / 'serp_google.json'
    processed_serp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(serp_src, processed_serp)
    saved_results = ROOT / 'output' / 'results' / slug
    result_overlay = overlay / 'output' / 'results' / slug
    if saved_results.is_dir():
        shutil.copytree(saved_results, result_overlay, dirs_exist_ok=True)
    else:
        result_overlay.mkdir(parents=True, exist_ok=True)
    # The existing inventory is the authority for the staged evidence list.
    staged_inventory = evidence_inventory(selection, root=overlay)
    if not staged_inventory.get('complete'):
        missing = [entry['kind'] + ':' + str(entry.get('side')) for entry in staged_inventory['entries']
                   if entry.get('status') != 'available']
        raise ValueError('Isolated evidence overlay is incomplete: ' + ', '.join(missing))
    inventory_path = version_dir / 'offline_evidence.json'
    _atomic_json(inventory_path, staged_inventory)
    refs = [{'kind': entry['kind'], 'side': entry['side'], 'path': entry['path'],
             'sha256': entry['sha256']} for entry in staged_inventory['entries']]
    record = {'schema_version': '1.1', 'investigation_id': investigation_id,
        'version_id': manifest['version_id'], 'keyword': selection['keyword'],
        'overlay_root': str(overlay.relative_to(_base(investigation_id))).replace('\\', '/'),
        'manifest_sha256': _sha(version_dir / 'manifest.json'),
        'offline_inventory': str(inventory_path.relative_to(_base(investigation_id))).replace('\\', '/'),
        'outputs': refs, 'created_at': _iso(), 'requests_made': 0}
    _atomic_json(marker, record)
    return overlay, record


def _record_completed_stage(investigation_id: str, version_dir: Path, manifest: dict,
                            inventory: dict, overlay_record: dict):
    checkpoint_path = _base(investigation_id) / 'workflow' / 'checkpoint.json'
    if not checkpoint_path.is_file():
        return
    state = _read(checkpoint_path)
    stage = state['stages']['evidence_collection']
    stage.update(status='completed', completed_at=_iso(), error=None,
        component='scripts.investigation_collection.execute_collection',
        input_fingerprint=manifest.get('input_fingerprint'),
        cache=('hit' if manifest['statistics'].get('cache_misses', 0) == 0 else 'mixed'),
        outputs=[{'path': str((version_dir / 'manifest.json').relative_to(_base(investigation_id))).replace('\\', '/'),
                  'sha256': _sha(version_dir / 'manifest.json')},
                 {'path': overlay_record['offline_inventory'],
                  'sha256': _sha(_base(investigation_id) / overlay_record['offline_inventory'])}],
        evidence_references=overlay_record['outputs'],
        request_summary=manifest['statistics'])
    stage.setdefault('attempts', []).append({'status': 'completed', 'finished_at': _iso(),
        'collection_version': manifest['version_id'], 'outputs': stage['outputs'],
        'requests': manifest['statistics']})
    state['current_stage'] = 'evidence_collection'
    state['completed_stages'] = [key for key, value in state['stages'].items()
                                 if value.get('status') == 'completed']
    state['updated_at'] = _iso()
    _atomic_json(checkpoint_path, state)


def _record_partial_stage(investigation_id: str, version_dir: Path, manifest: dict):
    checkpoint_path = _base(investigation_id) / 'workflow' / 'checkpoint.json'
    if not checkpoint_path.is_file():
        return
    state = _read(checkpoint_path)
    stage = state['stages']['evidence_collection']
    status = 'failed' if manifest.get('failures') else 'awaiting_review'
    stage.update(status=status, completed_at=None,
        error=({'kind': 'collector_failure', 'message': 'One or more collection operations failed; completed items were preserved.'}
               if status == 'failed' else
               {'kind': 'evidence_missing', 'message': 'Select an available collector explicitly to collect the remaining evidence.'}),
        component='scripts.investigation_collection.execute_collection',
        collection_version=manifest['version_id'], request_summary=manifest['statistics'],
        failure_references=manifest.get('failures', []),
        outputs=[{'path': str((version_dir / 'manifest.json').relative_to(_base(investigation_id))).replace('\\', '/'),
                  'sha256': _sha(version_dir / 'manifest.json')}])
    stage.setdefault('attempts', []).append({'status': status, 'finished_at': _iso(),
        'collection_version': manifest['version_id'], 'failures': manifest.get('failures', []),
        'statistics': manifest['statistics']})
    state['current_stage'] = 'evidence_collection'
    state['completed_stages'] = [key for key, value in state['stages'].items()
                                 if value.get('status') == 'completed']
    state['recovery_attempts'].extend([{'stage': 'evidence_collection', 'attempted_at': row['failed_at'],
        'action': 'preserve_successful_items_and_retry_missing', 'status': 'failed',
        'item_key': row.get('item_key'), 'message': row.get('message')}
        for row in manifest.get('failures', [])])
    state['updated_at'] = _iso()
    _atomic_json(checkpoint_path, state)


def execute_collection(investigation_id: str, *, collectors, authorize_paid_dataforseo=False,
                       authorize_external_page_requests=False, refresh=False, executors=None) -> dict:
    workflow_dir = _base(investigation_id) / 'workflow'
    with _CollectionStateLock(workflow_dir / '.collection_state.lock'):
        return _execute_collection_unlocked(investigation_id, collectors=collectors,
            authorize_paid_dataforseo=authorize_paid_dataforseo,
            authorize_external_page_requests=authorize_external_page_requests,
            refresh=refresh, executors=executors)


def _execute_collection_unlocked(investigation_id: str, *, collectors,
                       authorize_paid_dataforseo=False,
                       authorize_external_page_requests=False, refresh=False, executors=None) -> dict:
    if type(authorize_paid_dataforseo) is not bool or type(authorize_external_page_requests) is not bool:
        raise ValueError('Collector authorization flags must be boolean.')
    selected = tuple(dict.fromkeys(collectors or []))
    if any(value not in COLLECTORS for value in selected):
        raise ValueError('Select only supported evidence collectors.')
    if refresh and not selected:
        raise ValueError('Select a collector before requesting a fresh evidence version.')
    selection = serp_investigations.read_investigation(investigation_id)
    plan = plan_collection(investigation_id, collectors=selected, refresh=refresh)
    needed_dataforseo = plan['summary']['dataforseo_paid_requests']
    needed_external = plan['summary']['playwright_top_level_captures'] + plan['summary']['lighthouse_runs']
    if needed_dataforseo and not authorize_paid_dataforseo:
        raise CollectionAuthorizationRequired('This action may make ' + str(needed_dataforseo) +
            ' paid DataForSEO requests. Explicit paid-request authorization is required.', plan)
    if needed_external and not authorize_external_page_requests:
        raise CollectionAuthorizationRequired('This action may make ' + str(needed_external) +
            ' external page operations (Playwright/Lighthouse). Explicit external-request authorization is required.', plan)

    active_dir, active_manifest = _active_manifest(investigation_id)
    if (not refresh and active_dir and active_manifest and active_manifest.get('status') == 'completed' and
            all((active_manifest.get('items') or {}).get(row['item']['key'], {}).get('status') == 'completed'
                for row in plan['_plans'])):
        overlay = active_dir / 'root' / 'phase1_1_overlay.json'
        if overlay.is_file():
            record = _read(overlay)
            if record.get('manifest_sha256') == _sha(active_dir / 'manifest.json'):
                return {'schema_version': '1.1', 'investigation_id': investigation_id,
                    'version_id': active_manifest['version_id'], 'status': 'completed',
                    'items': [{'key': key, 'status': value.get('status'), 'cache_status': value.get('cache_status'),
                               'sha256': value.get('sha256')} for key, value in active_manifest['items'].items()],
                    'failures': active_manifest.get('failures', []),
                    'statistics': active_manifest['statistics'], 'overlay': record,
                    'requests_made': active_manifest['statistics']['paid_requests_made'],
                    'external_page_captures': active_manifest['statistics']['playwright_top_level_captures'],
                    'lighthouse_runs': active_manifest['statistics']['lighthouse_runs'],
                    'estimated_cost_usd': active_manifest['statistics'].get('reported_cost_usd')}

    version_dir, manifest = _collection_version(investigation_id, refresh)
    manifest['refresh'] = refresh
    manifest['collector_selection'] = list(selected)
    manifest['input_fingerprint'] = _digest({'investigation_id': investigation_id,
        'selection': selection, 'collectors': selected,
        'items': [(row['item']['key'], row['item']['context_fingerprint']) for row in plan['_plans']]})
    manifest.setdefault('attempts', []).append({'started_at': _iso(), 'collectors': list(selected), 'refresh': refresh})
    manifest['status'] = 'running'
    manifest['completed_at'] = None
    statistics = manifest.setdefault('statistics', {})
    for key, default in {
        'operation_attempts': 0, 'dataforseo_transmission_attempts': 0,
        'dataforseo_http_responses_received': 0, 'dataforseo_transmission_outcome_unknown': 0,
        'api_confirmed_charges_usd': 0.0, 'api_confirmed_charge_records': 0,
    }.items():
        statistics.setdefault(key, default)
    # Persist a visible state for every required item before any adapter starts.
    for planned in plan['_plans']:
        item = planned['item']
        force = refresh and item['collector'] in selected
        existing = _current_version_item(item, version_dir, manifest)
        if existing and not force:
            continue
        entry = manifest['items'].setdefault(item['key'], {
            'kind': item['kind'], 'side': item['side'], 'collector': item['collector'],
            'scope': item['scope'], 'target': item['target'],
            'context_fingerprint': item['context_fingerprint'], 'attempts': [],
        })
        if planned.get('candidate') and not force:
            entry['status'] = 'pending'
        elif item['collector'] in selected:
            entry['status'] = 'pending'
        else:
            entry['status'] = 'skipped'
            entry['finished_at'] = _iso()
        entry.setdefault('attempts', [])
        entry['attempt_count'] = len(entry['attempts'])
    _persist_collection_manifest(investigation_id, version_dir, manifest)
    executors = executors or {}
    failed = []
    for planned in plan['_plans']:
        item = planned['item']
        existing = _current_version_item(item, version_dir, manifest)
        force = refresh and item['collector'] in selected
        if existing and not force:
            manifest['statistics']['evidence_reuse_hits'] += 1
            continue
        should_recollect = item['collector'] in selected and (force or planned['status'] in ('missing', 'refresh_required'))
        if planned.get('candidate') and not force:
            current = manifest['items'].setdefault(item['key'], {'attempts': []})
            current['status'] = 'processing'
            current['started_at'] = current.get('started_at') or _iso()
            _persist_collection_manifest(investigation_id, version_dir, manifest)
            candidate = planned['candidate']
            source = candidate.get('raw_path')
            source_meta = candidate.get('metadata_path')
            raw = candidate['raw']
            source_cache = candidate.get('request_cache_path')
            if source_cache:
                cache_status = 'existing_dataforseo_request_cache'
                source = None
            else:
                cache_status = candidate.get('reuse_source', 'saved_evidence')
            _save_item(version_dir, manifest, item, raw,
                cache_status=cache_status, source_path=source, source_meta=source_meta)
            continue
        if not should_recollect:
            entry = manifest['items'].setdefault(item['key'], {'kind': item['kind'],
                'side': item['side'], 'collector': item['collector'], 'scope': item['scope'],
                'target': item['target'], 'context_fingerprint': item['context_fingerprint'], 'attempts': []})
            entry['status'] = 'skipped'
            entry['finished_at'] = _iso()
            _persist_collection_manifest(investigation_id, version_dir, manifest)
            continue
        attempt_id = uuid.uuid4().hex
        entry = manifest['items'].setdefault(item['key'], {'attempts': []})
        entry.setdefault('attempts', []).append({'attempt_id': attempt_id,
            'attempt_number': len(entry['attempts']) + 1, 'status': 'running', 'started_at': _iso(),
            'transmission_status': 'not_started'})
        entry['status'] = 'running'
        entry['attempt_count'] = len(entry['attempts'])
        entry['started_at'] = entry.get('started_at') or entry['attempts'][0]['started_at']
        entry['latest_started_at'] = entry['attempts'][-1]['started_at']
        entry['message'] = None
        entry['error_type'] = None
        manifest['statistics']['operation_attempts'] += 1
        _persist_collection_manifest(investigation_id, version_dir, manifest)

        def on_dataforseo_event(event):
            _collection_attempt_event(investigation_id, version_dir, manifest,
                                      item['key'], attempt_id, event)

        try:
            if item['collector'] == 'dataforseo':
                # Recheck a successful, fresh shared cache immediately before a
                # paid call in case another worker populated it after planning.
                cached = None if force else _request_cache_candidate(item)
                if cached:
                    raw, cost = cached['raw'], None
                    cache_status, paid, external = 'existing_dataforseo_request_cache', False, False
                    latest = manifest['items'][item['key']]['attempts'][-1]
                    latest['transmission_status'] = 'not_sent_cached'
                else:
                    if executors.get('dataforseo'):
                        raw, cost = _run_dataforseo(item, executors.get('dataforseo'))
                    else:
                        raw, cost = _run_dataforseo(item, event_callback=on_dataforseo_event)
                    cache_status, paid, external = ('explicit_refresh' if force else 'cache_miss'), True, False
            elif item['collector'] == 'playwright':
                raw, cost = _run_playwright(item, executors.get('playwright'))
                cache_status, paid, external = ('explicit_refresh' if force else 'cache_miss'), False, True
            else:
                raw, cost = _run_lighthouse(item, executors.get('lighthouse'))
                cache_status, paid, external = ('explicit_refresh' if force else 'cache_miss'), False, True
            entry = manifest['items'][item['key']]
            entry['status'] = 'processing'
            entry['api_status'] = raw.get('status_code') if isinstance(raw, dict) else None
            latest = entry['attempts'][-1]
            if latest.get('api_status') is None:
                latest['api_status'] = entry['api_status']
            latest['status'] = 'processing'
            _persist_collection_manifest(investigation_id, version_dir, manifest)
            _save_item(version_dir, manifest, item, raw, cache_status=cache_status,
                       paid=paid, external_operation=external, reported_cost=cost, attempt_id=attempt_id)
            entry = manifest['items'][item['key']]
            latest = entry['attempts'][-1]
            latest['status'] = 'completed'
            latest['finished_at'] = _iso()
            entry['attempt_count'] = len(entry['attempts'])
            if latest.get('transmission_status') == 'not_started':
                latest['transmission_status'] = 'not_sent_cached' if cache_status == 'existing_dataforseo_request_cache' else 'not_applicable'
            entry['transmission_status'] = latest.get('transmission_status')
            entry['http_status'] = latest.get('http_status')
            entry['api_status'] = latest.get('api_status')
            _persist_collection_manifest(investigation_id, version_dir, manifest)
        except CollectionPersistenceError:
            # Do not misreport a state-publication failure as a collector failure
            # or continue with in-memory state that was not durably published.
            raise
        except Exception as exc:
            message = getattr(exc, 'safe_message', None) or _safe_error_message(exc)
            diagnostic_reference = getattr(exc, 'diagnostic_reference', None)
            failed_row = {'item_key': item['key'], 'kind': item['kind'], 'side': item['side'],
                'collector': item['collector'], 'attempt_id': attempt_id,
                'failed_at': _iso(), 'error_type': type(exc).__name__, 'message': message}
            if diagnostic_reference:
                failed_row['diagnostic_reference'] = diagnostic_reference
            failed.append(failed_row)
            manifest['failures'].append(failed[-1])
            entry = manifest['items'][item['key']]
            latest = entry['attempts'][-1]
            latest.update({'status': 'failed', 'finished_at': failed[-1]['failed_at'],
                           'error_type': failed[-1]['error_type'], 'message': message})
            if diagnostic_reference:
                latest['diagnostic_reference'] = diagnostic_reference
            if latest.get('transmission_status') == 'not_started':
                latest['transmission_status'] = 'not_sent'
            entry.update({'status': 'failed', 'attempt_id': attempt_id, 'finished_at': failed[-1]['failed_at'],
                'error_type': failed[-1]['error_type'], 'message': message,
                'attempt_count': len(entry['attempts']), 'transmission_status': latest.get('transmission_status'),
                'http_status': latest.get('http_status'), 'api_status': latest.get('api_status')})
            if diagnostic_reference:
                entry['diagnostic_reference'] = diagnostic_reference
            manifest['statistics']['cache_misses'] += 1
            _persist_collection_manifest(investigation_id, version_dir, manifest)
            # Stop after the first failure. Earlier items are already durable;
            # retry reuses them and begins at this item.
            break

    # Recheck every output, including work reused from previous versions.
    for planned in plan['_plans']:
        item = planned['item']
        entry = manifest['items'].get(item['key'])
        if not entry or entry.get('status') != 'completed':
            continue
        raw_path = version_dir / entry.get('raw_file', '')
        meta_path = version_dir / entry.get('metadata_file', '')
        if (not raw_path.is_file() or _sha(raw_path) != entry.get('sha256') or
                not meta_path.is_file() or _sha(meta_path) != entry.get('metadata_sha256') or
                not _artifact_compatible(item, _read(raw_path), _read(meta_path), strict_context=False)):
            manifest['items'][item['key']] = {'status': 'failed', 'kind': item['kind'],
                'side': item['side'], 'collector': item['collector'], 'scope': item['scope'],
                'target': item['target'], 'context_fingerprint': item['context_fingerprint'],
                'error_type': 'artifact_integrity_failure', 'failed_at': _iso()}
            manifest['failures'].append({'item_key': item['key'], 'attempt_id': uuid.uuid4().hex,
                'failed_at': _iso(), 'error_type': 'artifact_integrity_failure',
                'message': 'Saved output or metadata hash failed verification.'})

    complete = all((manifest.get('items', {}).get(item['key']) or {}).get('status') == 'completed'
                   for item in _items(selection))
    manifest['status'] = 'completed' if complete else ('failed' if failed else 'awaiting_review')
    manifest['completed_at'] = _iso() if complete else None
    _persist_collection_manifest(investigation_id, version_dir, manifest)
    overlay_record = None
    if complete:
        try:
            overlay, overlay_record = _build_overlay(investigation_id, selection, version_dir, manifest)
        except Exception as exc:
            manifest['status'] = 'awaiting_review'
            manifest['completed_at'] = None
            manifest['failures'].append({'item_key': 'evidence_overlay', 'failed_at': _iso(),
                'error_type': type(exc).__name__, 'message': str(exc)[:1000]})
            _persist_collection_manifest(investigation_id, version_dir, manifest)
            _record_partial_stage(investigation_id, version_dir, manifest)
        else:
            _record_completed_stage(investigation_id, version_dir, manifest,
                                    _read(version_dir / 'offline_evidence.json'), overlay_record)
    else:
        _record_partial_stage(investigation_id, version_dir, manifest)
    return {'schema_version': '1.1', 'investigation_id': investigation_id,
        'version_id': manifest['version_id'], 'status': manifest['status'],
        'items': [{'key': key, 'status': value.get('status'), 'cache_status': value.get('cache_status'),
                   'sha256': value.get('sha256'), 'error_type': value.get('error_type'),
                   'message': value.get('message')}
                  for key, value in manifest['items'].items()],
        'failures': manifest['failures'], 'statistics': manifest['statistics'],
        'overlay': overlay_record,
        'requests_made': manifest['statistics']['paid_requests_made'],
        'external_page_captures': manifest['statistics']['playwright_top_level_captures'],
        'lighthouse_runs': manifest['statistics']['lighthouse_runs'],
        'estimated_cost_usd': None if not manifest['statistics']['reported_cost_usd'] else manifest['statistics']['reported_cost_usd']}


def active_evidence_root(investigation_id: str) -> Path | None:
    """Return only a completed, identity- and hash-verified isolated root."""
    version_dir, manifest = _active_manifest(investigation_id)
    if not version_dir or not manifest or manifest.get('status') != 'completed':
        return None
    overlay = version_dir / 'root'
    marker = overlay / 'phase1_1_overlay.json'
    if not marker.is_file():
        return None
    record = _read(marker)
    if record.get('investigation_id') != investigation_id or record.get('version_id') != manifest.get('version_id'):
        return None
    if record.get('manifest_sha256') != _sha(version_dir / 'manifest.json'):
        return None
    if not (version_dir / 'offline_evidence.json').is_file():
        return None
    return overlay


def public_plan(investigation_id: str, *, collectors=None, refresh=False) -> dict:
    plan = plan_collection(investigation_id, collectors=collectors, refresh=refresh)
    plan.pop('_plans', None)
    return plan
