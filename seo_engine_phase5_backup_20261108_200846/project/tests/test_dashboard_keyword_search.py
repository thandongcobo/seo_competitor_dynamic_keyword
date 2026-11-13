"""Phase 1 contract tests; fake collector responses are TEST ONLY, never shipped as data."""
import json
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts import dashboard_serp_search as search
from scripts.serve_dashboard import Handler


@pytest.fixture(autouse=True)
def reset_jobs():
    with search._LOCK:
        search._JOBS.clear()
        search._ACTIVE = None
    yield
    with search._LOCK:
        search._JOBS.clear()
        search._ACTIVE = None


def example_observation(keyword):
    return {
        'keyword': keyword, 'status': 'ok', 'datetime': datetime.now(timezone.utc).isoformat(),
        'collection_method': 'playwright_local_browser',
        'organic_results': [{'rank_group': 1, 'domain': 'example.org', 'title': 'Example', 'url': 'https://example.org/page'}],
    }


def test_keyword_validation():
    assert search.validate_keyword('  online   slots  ') == 'online slots'
    for invalid in ('', ' ', '\n', 'x' * 121, 123, None):
        with pytest.raises(ValueError):
            search.validate_keyword(invalid)
    for invalid in (0, 51, True, '20'):
        with pytest.raises(ValueError):
            search.start_search('aviator', invalid)


def test_saved_observations_are_keyword_isolated(tmp_path):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(example_observation('aviator')), encoding='utf-8')
    with patch.object(search, '_snapshot_path', return_value=path):
        result = search.read_snapshot('aviator')
        assert result['organic_results'][0]['url'] == 'https://example.org/page'
        with pytest.raises(ValueError, match='mismatched'):
            search.read_snapshot('other keyword')
        data = example_observation('aviator')
        data['organic_results'] = []
        path.write_text(json.dumps(data), encoding='utf-8')
        with pytest.raises(ValueError):
            search.read_snapshot('aviator')


def test_refresh_success_uses_collector_and_real_file_contract(tmp_path):
    path = tmp_path / 'result.json'
    def collector_run(command, **kwargs):
        assert '--refresh' in command
        assert kwargs['env']['SEO_KEYWORD'] == 'online slots'
        path.write_text(json.dumps(example_observation('online slots')), encoding='utf-8')
        return type('Completed', (), {'returncode': 0, 'stdout': 'ok'})()
    with patch.object(search, '_snapshot_path', return_value=path), patch.object(search.subprocess, 'run', side_effect=collector_run):
        job = search.start_search('online slots', 20)
        for _ in range(100):
            status = search.job_status(job['job_id'])
            if status['status'] != 'running':
                break
            threading.Event().wait(.01)
        assert status['status'] == 'completed'
        assert status['result']['keyword'] == 'online slots'
        assert status['result']['organic_results'][0]['domain'] == 'example.org'


def test_failed_refresh_never_returns_old_saved_snapshot(tmp_path):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(example_observation('aviator')), encoding='utf-8')
    with patch.object(search, '_snapshot_path', return_value=path), patch.object(search.subprocess, 'run', return_value=type('Completed', (), {'returncode': 2, 'stdout': 'challenge'})()):
        job = search.start_search('aviator', 10)
        for _ in range(100):
            status = search.job_status(job['job_id'])
            if status['status'] != 'running':
                break
            threading.Event().wait(.01)
        assert status['status'] == 'failed'
        assert 'result' not in status
        assert search.read_snapshot('aviator')['organic_results']


def test_only_one_active_search():
    blocker = threading.Event()
    def wait_collector(*args, **kwargs):
        blocker.wait(2)
        return type('Completed', (), {'returncode': 2, 'stdout': 'blocked'})()
    with patch.object(search.subprocess, 'run', side_effect=wait_collector):
        job = search.start_search('aviator')
        with pytest.raises(RuntimeError, match='already running'):
            search.start_search('other')
        blocker.set()
        for _ in range(100):
            if search.job_status(job['job_id'])['status'] != 'running': break
            threading.Event().wait(.01)


def test_http_api_validation_and_saved_result(tmp_path):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(example_observation('aviator')), encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(search, '_snapshot_path', return_value=path):
            with urlopen(base + '/api/serp/snapshot?keyword=aviator') as response:
                payload = json.load(response)
                assert payload['source'] == 'saved_google_playwright'
            with pytest.raises(HTTPError) as exc:
                urlopen(base + '/api/serp/snapshot?keyword=unrelated')
            assert exc.value.code == 400
        request = Request(base + '/api/serp/search', json.dumps({'keyword': '', 'depth': 20}).encode(), {'Content-Type': 'application/json'}, method='POST')
        with pytest.raises(HTTPError) as exc:
            urlopen(request)
        assert exc.value.code == 400
        with pytest.raises(HTTPError) as exc:
            urlopen(base + '/api/serp/jobs/nonexistent')
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_start_returns_job_and_polling_contract():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    job = {'job_id': 'test-job-id', 'keyword': 'online slots', 'depth': 20,
           'status': 'running', 'started_at': '2026-10-20T10:00:00+00:00'}
    try:
        with patch.object(search, 'start_search', return_value=job) as mocked_start, patch.object(search, 'job_status', return_value=job):
            req = Request(base + '/api/serp/search', json.dumps({'keyword': 'online slots', 'depth': 20}).encode(),
                          {'Content-Type': 'application/json'}, method='POST')
            with urlopen(req) as response:
                assert response.status == 202
                assert json.load(response)['job_id'] == 'test-job-id'
            mocked_start.assert_called_once_with('online slots', 20)
            with urlopen(base + '/api/serp/jobs/test-job-id') as response:
                assert json.load(response)['status'] == 'running'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
