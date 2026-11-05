"""Live Google keyword searches for the local dashboard (no paid API calls).

This is a thin, asynchronous adapter around the existing CLI collector. A failed
refresh never returns an older snapshot as if it were a new observation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config.settings import ROOT, keyword_slug
from config.settings import settings
from collectors.tracked_serp import discovery_state

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_ACTIVE: str | None = None
_MAX_JOBS = 40
_TIMEOUT_SECONDS = 600  # Up to ten Google pages may be needed to locate the tracked domain.


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_keyword(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('Keyword must be text.')
    keyword = ' '.join(value.split())
    if not 1 <= len(keyword) <= 120 or any(ord(ch) < 32 or ord(ch) == 127 for ch in keyword):
        raise ValueError('Enter a keyword between 1 and 120 characters without control characters.')
    return keyword


def _snapshot_path(keyword: str) -> Path:
    return ROOT / 'data' / 'raw' / 'serp' / f'{keyword_slug(keyword)}_google_playwright.json'


def read_snapshot(keyword: str) -> dict:
    """Return only an actual saved observation matching the requested keyword."""
    path = _snapshot_path(validate_keyword(keyword))
    if not path.is_file():
        raise FileNotFoundError('No saved Google results exist for this keyword.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or
            data.get('keyword', '').casefold() != keyword.casefold() or
            data.get('status') not in ('ok', 'partial') or
            data.get('collection_method') != 'playwright_local_browser' or
            not isinstance(data.get('organic_results'), list) or
            not data['organic_results']):
        raise ValueError('Saved search data is missing, mismatched or not a successful Google observation.')
    tracked = data.get('tracked_site')
    if not isinstance(tracked, dict):
        # Older snapshots are real observations; derive a clearly labelled
        # tracked-site lookup without recollecting or altering the rankings.
        tracked = discovery_state(data['organic_results'], settings.our_domain,
                                  data.get('depth_requested') or len(data['organic_results']),
                                  max(data.get('depth_collected') or len(data['organic_results']),
                                      data.get('depth_requested') or 0))
        tracked['derived_from_saved_results'] = True
    return {
        'keyword': data['keyword'],
        'status': data['status'],
        'collected_at': data.get('datetime'),
        'search_url': data.get('search_url'),
        'location_note': data.get('location_note'),
        'depth_requested': data.get('depth_requested'),
        'depth_collected': data.get('depth_collected', len(data['organic_results'])),
        'pages_completed': data.get('pages_completed'),
        'stop_reason': data.get('stop_reason'),
        'maximum_search_depth': data.get('maximum_search_depth'),
        'tracked_site': tracked,
        'validation': data.get('validation'),
        'serp_diagnostics_enabled': settings.serp_diagnostics_enabled,
        'diagnostics': data.get('diagnostics') if settings.serp_diagnostics_enabled else None,
        'previous_observation_comparison': data.get('previous_observation_comparison') if settings.serp_diagnostics_enabled else None,
        'organic_results': [
            {'rank_group': row.get('rank_group'), 'domain': row.get('domain'),
             'title': row.get('title'), 'url': row.get('url')}
            for row in data['organic_results']
            if isinstance(row, dict) and row.get('domain') and row.get('url')
        ],
        'source': 'saved_google_playwright',
    }


def _run(job_id: str, keyword: str, depth: int) -> None:
    global _ACTIVE
    try:
        env = dict(os.environ, SEO_KEYWORD=keyword, SEO_NAMESPACE_OUTPUT='1')
        command = [sys.executable, '-m', 'scripts.collect_team_serp', '--refresh', '--depth', str(depth)]
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=_TIMEOUT_SECONDS, check=False, errors='replace')
        if completed.returncode != 0:
            raise RuntimeError(f'Google collection failed (exit {completed.returncode}). ' +
                               (completed.stdout or '')[-650:])
        result = read_snapshot(keyword)
        # Verify this is the observation produced by THIS job, not an earlier snapshot.
        collected_at = datetime.fromisoformat(result['collected_at'])
        started_at = datetime.fromisoformat(_JOBS[job_id]['started_at'])
        if collected_at < started_at:
            raise RuntimeError('Collector did not produce a fresh Google snapshot.')
        with _LOCK:
            _JOBS[job_id].update(status='completed', finished_at=_utc(), result=result)
    except subprocess.TimeoutExpired:
        with _LOCK:
            _JOBS[job_id].update(status='failed', finished_at=_utc(), error='Google search timed out after 10 minutes. Check the Chrome window and try again.')
    except Exception as exc:
        with _LOCK:
            _JOBS[job_id].update(status='failed', finished_at=_utc(), error=str(exc)[:900])
    finally:
        with _LOCK:
            if _ACTIVE == job_id:
                _ACTIVE = None


def start_search(keyword: object, depth: object = 20) -> dict:
    global _ACTIVE
    keyword = validate_keyword(keyword)
    if type(depth) is not int or depth not in (10, 20, 50):
        raise ValueError('Search depth must be 10, 20 or 50 organic results.')
    with _LOCK:
        if _ACTIVE is not None:
            raise RuntimeError('A Google search is already running. Wait for it to finish before starting another.')
        job_id = uuid.uuid4().hex
        job = {'job_id': job_id, 'keyword': keyword, 'depth': depth,
               'status': 'running', 'started_at': _utc(), 'finished_at': None}
        _JOBS[job_id] = job
        _ACTIVE = job_id
        if len(_JOBS) > _MAX_JOBS:
            for key in list(_JOBS):
                if key != _ACTIVE and _JOBS[key]['status'] != 'running':
                    del _JOBS[key]
                    if len(_JOBS) <= _MAX_JOBS:
                        break
    try:
        threading.Thread(target=_run, args=(job_id, keyword, depth), daemon=True).start()
    except Exception:
        with _LOCK:
            _JOBS.pop(job_id, None)
            _ACTIVE = None
        raise
    return dict(job)


def job_status(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None
