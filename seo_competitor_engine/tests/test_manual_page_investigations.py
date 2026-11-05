"""Offline-only manual exact-page investigations, using real saved Aviator evidence."""
import json
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from config.settings import ROOT
from scripts import serp_investigations as si
from scripts.serve_dashboard import Handler


@pytest.fixture
def isolated(tmp_path):
    with patch.object(si, 'INVESTIGATIONS', tmp_path / 'investigations'):
        yield


def test_saved_aviator_evidence_matches_exact_urls_without_calls(isolated):
    manifest = si.create_page_investigation('aviator',
        'https://www.hollywoodbets.net/aviator', 'https://www.betway.co.za/aviator')
    assert manifest['ours']['rank'] == 2
    assert manifest['benchmark']['rank'] == 1
    assert manifest['status'] == 'selected_not_analyzed'
    assert si.read_investigation(manifest['investigation_id']) == manifest
    inventory = si.read_offline_evidence(manifest['investigation_id'])
    assert inventory['requests_made'] == 0
    assert inventory['complete']
    assert inventory['available'] == 12
    assert all(entry['sha256'] for entry in inventory['entries'])
    assert all((ROOT / entry['path']).is_file() for entry in inventory['entries'])


def test_reverse_selection_binds_real_data_by_target_not_old_side(isolated):
    manifest = si.create_page_investigation('aviator',
        'https://www.betway.co.za/aviator', 'https://www.hollywoodbets.net/aviator')
    inventory = si.read_offline_evidence(manifest['investigation_id'])
    assert inventory['complete']
    ours_ranked = next(e for e in inventory['entries'] if e['kind'] == 'labs_ranked_keywords' and e['side'] == 'ours')
    assert ours_ranked['path'].endswith('aviator_ranked_benchmark.json')


def test_different_page_same_domain_never_reuses_aviator_page_evidence(isolated):
    manifest = si.create_page_investigation('aviator',
        'https://www.hollywoodbets.net/some-other-page', 'https://www.betway.co.za/aviator')
    assert manifest['ours']['rank'] is None
    inventory = si.read_offline_evidence(manifest['investigation_id'])
    for kind in ('playwright_page', 'backlinks_page_summary', 'lighthouse_mobile'):
        assert next(e for e in inventory['entries'] if e['side'] == 'ours' and e['kind'] == kind)['status'] == 'missing_or_target_mismatch'
    assert not inventory['complete']


def test_arbitrary_keyword_and_two_urls_work_without_saved_serp(isolated):
    manifest = si.create_page_investigation('new unique keyword offline test 2026',
        'https://first-example.org/page', 'https://second-example.org/page')
    assert manifest['serp_sha256'] is None
    assert manifest['ours']['rank'] is None
    assert si.read_offline_evidence(manifest['investigation_id'])['available'] == 0


def test_same_domain_different_pages_allowed_but_same_url_rejected(isolated):
    m = si.create_page_investigation('aviator',
        'https://www.betway.co.za/aviator', 'https://www.betway.co.za/other')
    assert m['ours']['domain'] == m['benchmark']['domain']
    with pytest.raises(ValueError, match='different'):
        si.create_page_investigation('aviator', 'https://www.betway.co.za/aviator',
                                      'https://www.betway.co.za/aviator/')


@pytest.mark.parametrize('bad', ['http://localhost/page', 'http://127.0.0.1/page',
    'https://10.0.0.1/page', 'file:///etc/passwd', 'https://user:pass@example.com/page',
    'https://example.com:8080/path', 'https://bad host.com/page'])
def test_reject_unsafe_urls(bad):
    with pytest.raises(ValueError):
        si.validate_public_page_url(bad)


def test_stale_fingerprint_is_rejected(isolated):
    with pytest.raises(ValueError, match='changed'):
        si.create_page_investigation('aviator', 'https://www.hollywoodbets.net/aviator',
                                     'https://www.betway.co.za/aviator', '0'*64)


def test_manual_http_create_and_evidence_endpoint(isolated):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        payload = {'keyword': 'aviator', 'ours_url': 'https://www.hollywoodbets.net/aviator',
                   'benchmark_url': 'https://www.betway.co.za/aviator'}
        req = Request(base + '/api/investigations/manual', json.dumps(payload).encode(),
                      {'Content-Type': 'application/json'}, method='POST')
        with urlopen(req) as resp:
            assert resp.status == 201
            result = json.load(resp)
        with urlopen(base + '/api/investigations/' + result['investigation_id'] + '/offline-evidence') as resp:
            assert json.load(resp)['available'] == 12
        with urlopen(base + '/api/investigations/' + result['investigation_id']) as resp:
            assert json.load(resp) == result
        payload['ours_url'] = 'http://localhost/private'
        req = Request(base + '/api/investigations/manual', json.dumps(payload).encode(),
                      {'Content-Type': 'application/json'}, method='POST')
        with pytest.raises(HTTPError) as err:
            urlopen(req)
        assert err.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
