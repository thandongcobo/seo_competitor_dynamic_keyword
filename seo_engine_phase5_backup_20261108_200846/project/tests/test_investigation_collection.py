"""Offline tests for investigation-scoped evidence collection adapters."""
import json
from threading import Thread

import pytest

from config.settings import keyword_slug
from scripts import investigation_collection as collection
from scripts import investigation_workflow as workflow
from scripts import investigation_offline
from scripts import serp_investigations


@pytest.fixture
def collection_case(tmp_path, monkeypatch):
    investigations = tmp_path / 'investigations'
    root = tmp_path / 'engine'
    ident = 'b' * 32
    folder = investigations / ident
    folder.mkdir(parents=True)
    selection = {
        'schema_version': '1.1', 'investigation_id': ident,
        'keyword': 'synthetic trail shoes', 'source': 'manual_exact_webpage_urls',
        'ours': {'domain': 'trail.example', 'url': 'https://trail.example/products/road-shoe'},
        'benchmark': {'domain': 'pace.example', 'url': 'https://pace.example/guides/road-running'},
    }
    (folder / 'selection.json').write_text(json.dumps(selection), encoding='utf-8')
    (folder / 'offline_evidence.json').write_text(json.dumps({
        'investigation_id': ident, 'entries': []}), encoding='utf-8')
    root.mkdir()
    slug = keyword_slug(selection['keyword'])
    serp = root / 'data' / 'processed' / slug / 'serp_google.json'
    serp.parent.mkdir(parents=True)
    serp.write_text(json.dumps({'keyword': selection['keyword'], 'organic_results': []}), encoding='utf-8')
    (root / 'output' / 'results' / slug).mkdir(parents=True)
    monkeypatch.setattr(serp_investigations, 'INVESTIGATIONS', investigations)
    monkeypatch.setattr(collection, 'ROOT', root)
    real_inventory = investigation_offline.evidence_inventory
    monkeypatch.setattr(collection, 'evidence_inventory',
                        lambda value, root=root: real_inventory(value, root=root))
    # Simulate application initialization and durable checkpoint storage.
    workflow.get_state(ident)
    return ident, folder, selection, root


def _mock_for(item, fail_page_once, calls):
    calls.append(item['key'])
    if item['collector'] == 'dataforseo':
        if item['kind'] == 'labs_ranked_keywords':
            data = {'target': item['target']}
        elif item['kind'] == 'labs_domain_intersection':
            data = {'target1': item['target'][0], 'target2': item['target'][1]}
        elif item['kind'] == 'labs_search_intent':
            data = {'keywords': [item['keyword']]}
        else:
            data = {'target': item['target']}
        return {'status_code': 20000, 'tasks': [{'status_code': 20000, 'data': data}], 'cost': 0.01}
    if item['collector'] == 'playwright':
        if item['side'] == 'benchmark' and fail_page_once[0]:
            fail_page_once[0] = False
            raise RuntimeError('simulated competitor capture failure')
        return {'keyword': item['keyword'], 'requested_url': item['target'],
                'final_url': item['target'], 'ranking_url': item['target'],
                'extraction_status': 'complete', 'crawl_failed': False, 'blocked': False,
                'title': 'Synthetic page', 'headings': [], 'links': []}
    return {'lighthouseVersion': '12.0.0', 'requestedUrl': item['target'],
            'finalDisplayedUrl': item['target'], 'categories': {}}


def test_collector_plan_is_context_specific_and_general_run_makes_no_calls(collection_case, monkeypatch):
    ident, _, selection, _ = collection_case
    assert len(collection._items(selection)) == 12
    plan = collection.plan_collection(ident, collectors=[])
    assert plan['summary']['required_items'] == 12
    assert plan['summary']['missing_items'] == 12
    assert plan['summary']['dataforseo_paid_requests'] == 0
    with pytest.raises(collection.CollectionAuthorizationRequired):
        collection.execute_collection(ident, collectors=['playwright'])
    calls = []
    result = collection.execute_collection(ident, collectors=[], executors={
        'dataforseo': lambda item: calls.append(item),
        'playwright': lambda item: calls.append(item),
        'lighthouse': lambda item: calls.append(item),
    })
    assert result['status'] == 'awaiting_review'
    assert calls == []
    other = dict(selection)
    other['keyword'] = 'synthetic mountain backpacks'
    assert collection._items(other)[0]['context_fingerprint'] != collection._items(selection)[0]['context_fingerprint']
    other = json.loads(json.dumps(selection))
    other['ours']['url'] = 'https://trail.example/products/different-shoe'
    assert collection._items(other)[3]['context_fingerprint'] != collection._items(selection)[3]['context_fingerprint']


def test_successful_exact_dataforseo_request_cache_is_reused(collection_case, tmp_path, monkeypatch):
    ident, _, selection, _ = collection_case
    from collectors import request_cache
    monkeypatch.setattr(request_cache, 'CACHE_DIR', tmp_path / 'cache')
    item = collection._items(selection)[0]
    response = {'status_code': 20000, 'tasks': [{'status_code': 20000,
                'data': {'target': item['target']}}]}
    path = request_cache.cache_path('POST', item['endpoint'], item['payload'])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'method': 'POST', 'path': item['endpoint'],
        'payload': item['payload'], 'cached_at_utc': collection._iso(),
        'response': response}), encoding='utf-8')
    cached = collection._request_cache_candidate(item)
    assert cached and cached['reuse_source'] == 'existing_dataforseo_request_cache'
    assert cached['raw'] == response
    response['status_code'] = 50000
    path.write_text(json.dumps({'method': 'POST', 'path': item['endpoint'],
        'payload': item['payload'], 'cached_at_utc': collection._iso(),
        'response': response}), encoding='utf-8')
    assert collection._request_cache_candidate(item) is None


def test_dashboard_plan_is_read_only_and_execute_requires_authorization(collection_case):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from scripts.serve_dashboard import Handler

    ident, _, _, _ = collection_case
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}/api/investigations/{ident}/workflow'
    try:
        with urlopen(base + '/collection-plan') as response:
            plan = json.load(response)
        assert plan['summary']['required_items'] == 12
        assert plan['summary']['dataforseo_paid_requests'] == 8
        # GET exposes the cost/request plan only; the rejected POST never reaches a collector.
        request = Request(base + '/collection/execute', data=json.dumps({
            'collectors': ['dataforseo'], 'authorize_paid_dataforseo': False,
            'authorize_external_page_requests': False}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
        payload = json.loads(error.value.read())
        assert 'paid DataForSEO requests' in payload['error']
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_concurrent_explicit_collection_requests_are_serialized(collection_case, monkeypatch):
    ident, _, _, _ = collection_case
    calls = []
    fail_page_once = [False]
    monkeypatch.setattr(collection, '_run_dataforseo',
        lambda item, executor=None: (_mock_for(item, fail_page_once, calls), 0.01))
    monkeypatch.setattr(collection, '_run_playwright',
        lambda item, executor=None: (_mock_for(item, fail_page_once, calls), None))
    monkeypatch.setattr(collection, '_run_lighthouse',
        lambda item, executor=None: (_mock_for(item, fail_page_once, calls), None))
    results = []
    errors = []

    def collect():
        try:
            results.append(workflow.collect_evidence(ident, collectors=list(collection.COLLECTORS),
                authorize_paid_dataforseo=True, authorize_external_page_requests=True)['collection'])
        except Exception as exc:
            errors.append(exc)

    workers = [Thread(target=collect), Thread(target=collect)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert not errors
    assert len(results) == 2 and all(row['status'] == 'completed' for row in results)
    assert len(calls) == 12


def test_partial_collection_survives_restart_and_retries_only_missing_item(collection_case):
    ident, folder, _, _ = collection_case
    calls = []
    fail_page_once = [True]
    executors = {
        'dataforseo': lambda item: _mock_for(item, fail_page_once, calls),
        'playwright': lambda item: _mock_for(item, fail_page_once, calls),
        'lighthouse': lambda item: _mock_for(item, fail_page_once, calls),
    }
    kwargs = {'collectors': list(collection.COLLECTORS), 'authorize_paid_dataforseo': True,
              'authorize_external_page_requests': True, 'executors': executors}
    first = collection.execute_collection(ident, **kwargs)
    assert first['status'] == 'failed'
    assert first['failures'][0]['item_key'] == 'playwright_page:benchmark'
    manifest_path = folder / 'workflow' / 'collections' / first['version_id'] / 'manifest.json'
    saved = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert saved['items']['playwright_page:ours']['status'] == 'completed'
    assert saved['items']['playwright_page:benchmark']['status'] == 'failed'
    # Reopen workflow to exercise restart recovery from the persisted manifest.
    restarted = workflow.get_state(ident)
    assert restarted['stages']['evidence_collection']['status'] == 'failed'
    prior_calls = len(calls)
    second = collection.execute_collection(ident, **kwargs)
    assert second['status'] == 'completed'
    assert calls[prior_calls:] == ['playwright_page:benchmark',
        'lighthouse_mobile:benchmark', 'labs_domain_intersection:shared', 'labs_search_intent:shared']
    assert second['statistics']['paid_requests_made'] == 8
    assert second['statistics']['playwright_top_level_captures'] == 3
    assert second['statistics']['lighthouse_runs'] == 2
    assert second['overlay'] and collection.active_evidence_root(ident)
    assert second['statistics']['cache_misses'] == 13
    assert second['statistics']['evidence_reuse_hits'] == 8
    # A completed immutable version reopens without mutating its manifest or collecting again.
    before = manifest_path.read_bytes()
    third = collection.execute_collection(ident, collectors=[], executors={})
    assert third['status'] == 'completed'
    assert manifest_path.read_bytes() == before


def test_refresh_creates_a_new_version_without_replacing_history(collection_case):
    ident, folder, original_selection, _ = collection_case
    calls = []
    fail_page_once = [False]
    executors = {name: (lambda item, failure=fail_page_once: _mock_for(item, failure, calls))
                 for name in collection.COLLECTORS}
    first = collection.execute_collection(ident, collectors=list(collection.COLLECTORS),
        authorize_paid_dataforseo=True, authorize_external_page_requests=True, executors=executors)
    assert first['status'] == 'completed'
    old_manifest = folder / 'workflow' / 'collections' / first['version_id'] / 'manifest.json'
    old_bytes = old_manifest.read_bytes()
    calls.clear()
    second = collection.execute_collection(ident, collectors=['playwright'], refresh=True,
        authorize_external_page_requests=True, executors=executors)
    assert second['version_id'] != first['version_id']
    assert second['status'] == 'completed'
    assert old_manifest.read_bytes() == old_bytes
    assert calls == ['playwright_page:ours', 'playwright_page:benchmark']
    branch_result = workflow.branch_competitor(ident, 'https://newpace.example/reviews/road-shoes')
    branch_id = branch_result['investigation']['investigation_id']
    branch_plan = collection.plan_collection(branch_id, collectors=[])
    compatible = [row for row in branch_plan['items'] if row['reuse_source'] == 'compatible_investigation_version']
    assert len(compatible) == 6  # five exact Hollywoodbets items plus keyword-level search intent
    assert all(row['side'] in (None, 'ours') for row in compatible)
    assert serp_investigations.read_investigation(ident) == original_selection

