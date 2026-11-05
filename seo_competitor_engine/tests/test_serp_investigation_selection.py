"""Selection tests use synthetic observations only inside the test runner."""
import json
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts import dashboard_serp_search, serp_investigations
from scripts.serve_dashboard import Handler


@pytest.fixture
def snapshot(tmp_path):
    file = tmp_path / 'serp.json'
    file.write_text(json.dumps({
        'keyword': 'aviator', 'status': 'ok', 'datetime': datetime.now(timezone.utc).isoformat(),
        'collection_method': 'playwright_local_browser',
        'organic_results': [
            {'rank_group': 1, 'domain': 'betway.co.za', 'url': 'https://betway.co.za/aviator', 'title': 'Betway'},
            {'rank_group': 2, 'domain': 'hollywoodbets.net', 'url': 'https://hollywoodbets.net/aviator', 'title': 'Hollywoodbets'},
            {'rank_group': 3, 'domain': 'betway.co.za', 'url': 'https://betway.co.za/second', 'title': 'Other Betway'},
            {'rank_group': 4, 'domain': 'third.org', 'url': 'https://third.org/aviator', 'title': 'Third'},
        ],
    }), encoding='utf-8')
    with patch.object(dashboard_serp_search, '_snapshot_path', return_value=file), \
         patch.object(serp_investigations, '_snapshot_path', return_value=file), \
         patch.object(serp_investigations, 'INVESTIGATIONS', tmp_path / 'investigations'):
        yield file


def test_options_preserve_first_ranking_url_and_observed_order(snapshot):
    options = serp_investigations.selection_options('aviator')
    assert [x['domain'] for x in options['options']] == ['betway.co.za', 'hollywoodbets.net', 'third.org']
    assert options['options'][0]['url'] == 'https://betway.co.za/aviator'


def test_selection_is_immutable_and_pair_is_flexible(snapshot):
    options = serp_investigations.selection_options('aviator')
    manifest = serp_investigations.create_investigation('aviator', 'third.org', 'hollywoodbets.net', options['snapshot_fingerprint'])
    assert manifest['ours']['url'] == 'https://third.org/aviator'
    assert manifest['benchmark']['rank'] == 2
    assert manifest['status'] == 'selected_not_analyzed'
    assert serp_investigations.read_investigation(manifest['investigation_id']) == manifest
    with pytest.raises(ValueError, match='different'):
        serp_investigations.create_investigation('aviator', 'third.org', 'third.org', options['snapshot_fingerprint'])
    with pytest.raises(ValueError, match='must appear'):
        serp_investigations.create_investigation('aviator', 'third.org', 'unknown.org', options['snapshot_fingerprint'])
    with pytest.raises(ValueError, match='changed'):
        serp_investigations.create_investigation('aviator', 'third.org', 'hollywoodbets.net', '0' * 64)


def test_snapshot_change_invalidates_selection(snapshot):
    options = serp_investigations.selection_options('aviator')
    data = json.loads(snapshot.read_text(encoding='utf-8'))
    data['organic_results'][0]['title'] = 'Changed title'
    snapshot.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        serp_investigations.create_investigation('aviator', 'third.org', 'hollywoodbets.net', options['snapshot_fingerprint'])


def test_http_options_and_create_selection(snapshot):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/api/serp/options?keyword=aviator') as resp:
            options = json.load(resp)
        payload = {'keyword': 'aviator', 'ours': 'hollywoodbets.net', 'benchmark': 'betway.co.za',
                   'snapshot_fingerprint': options['snapshot_fingerprint']}
        req = Request(base + '/api/investigations', json.dumps(payload).encode(),
                      {'Content-Type': 'application/json'}, method='POST')
        with urlopen(req) as resp:
            assert resp.status == 201
            manifest = json.load(resp)
        with urlopen(base + '/api/investigations/' + manifest['investigation_id']) as resp:
            assert json.load(resp) == manifest
        payload['benchmark'] = 'fake.org'
        req = Request(base + '/api/investigations', json.dumps(payload).encode(),
                      {'Content-Type': 'application/json'}, method='POST')
        with pytest.raises(HTTPError) as err:
            urlopen(req)
        assert err.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
