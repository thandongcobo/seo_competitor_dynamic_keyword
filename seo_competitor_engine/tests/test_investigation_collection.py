"""Offline tests for investigation-scoped evidence collection adapters."""
import json
import multiprocessing
from pathlib import Path
from threading import Event, Thread
import time

import pytest

from config.settings import keyword_slug
from scripts import investigation_collection as collection
from scripts import investigation_workflow as workflow
from scripts import investigation_offline
from scripts import serp_investigations


def _collection_persistence_process_writer(lock_path, target_path, writer_id, start_event, result_queue):
    try:
        start_event.wait(10)
        with collection._CollectionStateLock(Path(lock_path), timeout=10):
            for sequence in range(20):
                collection._atomic_json(Path(target_path), {
                    'writer': writer_id, 'sequence': sequence,
                    'payload': str(writer_id) * 256})
        result_queue.put((writer_id, None))
    except Exception as exc:
        result_queue.put((writer_id, f'{type(exc).__name__}: {exc}'))


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
    from collectors import request_cache
    monkeypatch.setattr(request_cache, 'CACHE_DIR', root / 'request-cache')
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
    assert collection.collection_status(ident)['summary']['skipped'] == 12
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
        with urlopen(base + '/collection-status') as response:
            status = json.load(response)
        assert status['summary']['required'] == 12
        assert status['summary']['pending'] == 12
        assert status['status'] == 'not_started'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_concurrent_explicit_collection_requests_are_serialized(collection_case, monkeypatch):
    ident, _, _, _ = collection_case
    calls = []
    fail_page_once = [False]
    monkeypatch.setattr(collection, '_run_dataforseo',
        lambda item, executor=None, **kwargs: (_mock_for(item, fail_page_once, calls), 0.01))
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
    status_after_failure = collection.collection_status(ident)
    assert status_after_failure['summary']['completed'] == 8
    assert status_after_failure['summary']['failed'] == 1
    assert status_after_failure['summary']['pending'] == 3
    failed_item = next(row for row in status_after_failure['items'] if row['key'] == 'playwright_page:benchmark')
    assert failed_item['status'] == 'failed' and 'simulated competitor capture failure' in failed_item['error']
    assert failed_item['attempt_count'] == 1 and failed_item['started_at'] and failed_item['completed_at']
    # Reopen workflow to exercise restart recovery from the persisted manifest.
    restarted = workflow.get_state(ident)
    assert restarted['stages']['evidence_collection']['status'] == 'failed'
    assert collection.collection_status(ident)['summary']['failed'] == 1
    prior_calls = len(calls)
    second = collection.execute_collection(ident, **kwargs)
    assert second['status'] == 'completed'
    assert calls[prior_calls:] == ['playwright_page:benchmark',
        'lighthouse_mobile:benchmark', 'labs_domain_intersection:shared', 'labs_search_intent:shared']
    assert second['statistics']['paid_requests_made'] == 8
    assert second['statistics']['playwright_top_level_captures'] == 2
    assert second['statistics']['lighthouse_runs'] == 2
    assert second['statistics']['operation_attempts'] == 13
    assert second['overlay'] and collection.active_evidence_root(ident)
    assert second['statistics']['cache_misses'] == 13
    assert second['statistics']['evidence_reuse_hits'] == 8
    # A completed immutable version reopens without mutating its manifest or collecting again.
    before = manifest_path.read_bytes()
    third = collection.execute_collection(ident, collectors=[], executors={})
    assert third['status'] == 'completed'
    assert manifest_path.read_bytes() == before


def test_incomplete_playwright_manifest_keeps_diagnostic_reference(collection_case):
    ident, folder, _, _ = collection_case
    diagnostic_reference = 'diagnostics/page_crawls/fixture/metadata.json'
    def incomplete(item):
        return {'keyword': item['keyword'], 'requested_url': item['target'],
            'final_url': item['target'], 'extraction_status': 'incomplete',
            'crawl_failed': True, 'blocked': False,
            'content_quality_reason': 'standardized_main_content_not_confirmed',
            'diagnostic_reference': diagnostic_reference}

    result = collection.execute_collection(ident, collectors=['playwright'],
        authorize_external_page_requests=True, executors={'playwright': incomplete})
    assert result['status'] == 'failed'
    assert result['failures'][0]['message'] == (
        'Playwright capture incomplete: standardized_main_content_not_confirmed.')
    assert result['failures'][0]['diagnostic_reference'] == diagnostic_reference
    manifest_path = folder / 'workflow' / 'collections' / result['version_id'] / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    item = manifest['items']['playwright_page:ours']
    assert item['status'] == 'failed'
    assert item['diagnostic_reference'] == diagnostic_reference
    assert item['attempts'][0]['diagnostic_reference'] == diagnostic_reference
    status_row = next(row for row in collection.collection_status(ident)['items']
        if row['key'] == 'playwright_page:ours')
    assert status_row['diagnostic_reference'] == diagnostic_reference


def test_collection_status_success_and_repeated_reads_do_not_start_collectors(collection_case, monkeypatch):
    ident, _, _, root = collection_case
    from collectors import request_cache
    monkeypatch.setattr(request_cache, 'CACHE_DIR', root / 'request-cache')
    calls = []
    fail_page_once = [False]
    executors = {name: (lambda item, name=name: _mock_for(item, fail_page_once, calls))
                 for name in collection.COLLECTORS}
    result = collection.execute_collection(ident, collectors=list(collection.COLLECTORS),
        authorize_paid_dataforseo=True, authorize_external_page_requests=True, executors=executors)
    assert result['status'] == 'completed'
    assert result['statistics']['operation_attempts'] == 12
    # Executor mocks return API-shaped bodies but do not represent HTTP transmissions.
    assert result['statistics']['dataforseo_http_responses_received'] == 0
    assert result['statistics']['api_confirmed_charge_records'] == 8
    assert result['statistics']['api_confirmed_charges_usd'] == pytest.approx(0.08)
    status = collection.collection_status(ident)
    assert status['summary']['required'] == 12
    assert status['summary']['completed'] == 12 and status['summary']['reused'] == 0
    assert status['summary']['failed'] == status['summary']['pending'] == 0
    assert all(row['attempt_count'] == 1 and row['started_at'] and row['completed_at'] for row in status['items'])
    before = len(calls)
    for _ in range(5):
        polled = collection.collection_status(ident)
        assert polled['status'] == 'completed'
        assert 'not a transmission count or proof of charges' in polled['request_accounting']['legacy_counter_note']
    assert len(calls) == before == 12


def test_collection_status_marks_reused_and_skipped_items(collection_case, monkeypatch):
    ident, _, _, root = collection_case
    from collectors import request_cache
    monkeypatch.setattr(request_cache, 'CACHE_DIR', root / 'request-cache')
    calls = []
    fail_page_once = [False]
    executors = {name: (lambda item, failure=fail_page_once: _mock_for(item, failure, calls))
                 for name in collection.COLLECTORS}
    first = collection.execute_collection(ident, collectors=list(collection.COLLECTORS),
        authorize_paid_dataforseo=True, authorize_external_page_requests=True, executors=executors)
    second = collection.execute_collection(ident, collectors=['playwright'], refresh=True,
        authorize_external_page_requests=True, executors=executors)
    assert second['status'] == 'completed'
    status = collection.collection_status(ident)
    assert status['summary']['reused'] == 10
    assert status['summary']['completed'] == 2
    assert status['summary']['required'] == 12


def test_collection_status_polls_running_manifest_without_duplicate_operations(collection_case, monkeypatch):
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen
    from scripts.serve_dashboard import Handler
    ident, _, _, root = collection_case
    from collectors import request_cache
    monkeypatch.setattr(request_cache, 'CACHE_DIR', root / 'request-cache')
    started, release, processing_started, processing_release = Event(), Event(), Event(), Event()
    calls = []
    fail_page_once = [False]
    executors = {}
    def dataforseo(item):
        calls.append(item['key'])
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return _mock_for(item, fail_page_once, [])
    executors['dataforseo'] = dataforseo
    executors['playwright'] = lambda item: _mock_for(item, fail_page_once, calls)
    executors['lighthouse'] = lambda item: _mock_for(item, fail_page_once, calls)
    original_save = collection._save_item
    paused = [False]
    def pause_first_save(*args, **kwargs):
        if not paused[0]:
            paused[0] = True
            processing_started.set()
            assert processing_release.wait(5)
        return original_save(*args, **kwargs)
    monkeypatch.setattr(collection, '_save_item', pause_first_save)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True); server_thread.start()
    results = []
    worker = Thread(target=lambda: results.append(collection.execute_collection(ident,
        collectors=list(collection.COLLECTORS), authorize_paid_dataforseo=True,
        authorize_external_page_requests=True, executors=executors)))
    try:
        worker.start(); assert started.wait(5)
        url = f'http://127.0.0.1:{server.server_port}/api/investigations/{ident}/workflow/collection-status'
        with urlopen(url) as response: running = json.load(response)
        assert running['status'] == 'running'
        assert running['summary']['running'] == 1 and running['summary']['pending'] == 11
        with urlopen(url) as response: assert json.load(response)['summary']['running'] == 1
        assert len(calls) == 1
        release.set(); assert processing_started.wait(5)
        with urlopen(url) as response: processing = json.load(response)
        assert processing['summary']['processing'] == 1
        assert len(calls) == 1
        processing_release.set(); worker.join(timeout=10)
        assert not worker.is_alive() and results[0]['status'] == 'completed'
        with urlopen(url) as response: final = json.load(response)
        assert final['status'] == 'completed' and final['summary']['completed'] == 12
        assert len(calls) == 12
    finally:
        release.set(); processing_release.set(); worker.join(timeout=5)
        server.shutdown(); server.server_close(); server_thread.join(timeout=3)


def test_atomic_json_writer_with_concurrent_readers(tmp_path):
    target = tmp_path / 'collection_active.json'
    collection._atomic_json(target, {'sequence': -1, 'payload': 'initial'})
    stop = Event()
    read_started = Event()
    read_errors = []
    reads = []

    def reader():
        while not stop.is_set():
            try:
                data = collection._read(target)
                assert isinstance(data.get('sequence'), int)
                reads.append(data['sequence'])
                read_started.set()
            except Exception as exc:
                read_errors.append(exc)
                stop.set()

    readers = [Thread(target=reader) for _ in range(4)]
    for thread in readers:
        thread.start()
    assert read_started.wait(3)
    write_errors = []
    try:
        for sequence in range(100):
            try:
                collection._atomic_json(target, {'sequence': sequence, 'payload': 'x' * 2048})
            except Exception as exc:
                write_errors.append(exc)
                break
    finally:
        stop.set()
        for thread in readers:
            thread.join(timeout=3)
    assert not read_errors
    assert not write_errors
    assert reads
    assert json.loads(target.read_text(encoding='utf-8'))['sequence'] == 99


def test_collection_state_lock_serializes_same_process_writers(tmp_path):
    lock_path = tmp_path / '.collection_state.lock'
    target = tmp_path / 'manifest.json'
    errors = []

    def writer(writer_id):
        try:
            with collection._CollectionStateLock(lock_path):
                for sequence in range(30):
                    collection._atomic_json(target, {
                        'writer': writer_id, 'sequence': sequence,
                        'payload': str(writer_id) * 1024})
        except Exception as exc:
            errors.append(exc)

    threads = [Thread(target=writer, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert json.loads(target.read_text(encoding='utf-8'))['sequence'] == 29
    assert not list(tmp_path.glob('manifest.json.*.tmp'))


def test_collection_state_lock_serializes_process_writers(tmp_path):
    context = multiprocessing.get_context('spawn')
    lock_path = tmp_path / '.collection_state.lock'
    target = tmp_path / 'manifest.json'
    start_event = context.Event()
    results = context.Queue()
    processes = [context.Process(target=_collection_persistence_process_writer,
        args=(str(lock_path), str(target), index, start_event, results)) for index in range(3)]
    for process in processes:
        process.start()
    start_event.set()
    outcomes = [results.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=10)
    assert all(process.exitcode == 0 for process in processes)
    assert all(error is None for _, error in outcomes)
    final = json.loads(target.read_text(encoding='utf-8'))
    assert final['writer'] in (0, 1, 2) and final['sequence'] == 19
    assert not list(tmp_path.glob('manifest.json.*.tmp'))


def test_atomic_json_retries_windows_sharing_violation(tmp_path, monkeypatch):
    if collection.os.name != 'nt':
        pytest.skip('Windows sharing-error semantics are platform-specific.')
    target = tmp_path / 'manifest.json'
    collection._atomic_json(target, {'valid': 'old'})
    original_replace = collection.os.replace
    attempts = []

    def fail_twice_then_replace(source, destination):
        attempts.append((source, destination))
        if len(attempts) <= 2:
            error = PermissionError(32, 'sharing violation', str(destination))
            error.winerror = 32
            raise error
        return original_replace(source, destination)

    monkeypatch.setattr(collection.os, 'replace', fail_twice_then_replace)
    collection._atomic_json(target, {'valid': 'new'})
    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding='utf-8')) == {'valid': 'new'}
    assert not list(tmp_path.glob('manifest.json.*.tmp'))


def test_atomic_json_retry_exhaustion_preserves_destination_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / 'collection_active.json'
    collection._atomic_json(target, {'version_id': 'previous'})
    monkeypatch.setattr(collection.time, 'sleep', lambda _: None)

    def always_share_locked(source, destination):
        error = PermissionError(5, 'access denied', str(destination))
        error.winerror = 5
        raise error

    monkeypatch.setattr(collection.os, 'replace', always_share_locked)
    with pytest.raises(collection.CollectionPersistenceError, match='Unable to atomically persist'):
        collection._atomic_json(target, {'version_id': 'new'})
    assert json.loads(target.read_text(encoding='utf-8')) == {'version_id': 'previous'}
    assert not list(tmp_path.glob('collection_active.json.*.tmp'))


def test_manifest_pointer_publish_failure_rolls_back_to_restartable_state(collection_case, tmp_path, monkeypatch):
    ident, _, _, _ = collection_case
    version_id = '20261112T000000000000Zabcdef12'
    version_dir = collection._collection_root(ident) / version_id
    version_dir.mkdir(parents=True)
    initial = {'schema_version': '1.1', 'investigation_id': ident,
        'version_id': version_id, 'status': 'running', 'items': {}, 'failures': [],
        'statistics': {'cache_misses': 0}}
    collection._persist_collection_manifest(ident, version_dir, initial)
    pointer_path = collection._active_path(ident)
    original_pointer = pointer_path.read_text(encoding='utf-8')
    updated = {**initial, 'status': 'completed'}
    original_replace = collection.os.replace
    monkeypatch.setattr(collection.time, 'sleep', lambda _: None)

    def block_pointer_only(source, destination):
        if Path(destination) == pointer_path:
            error = PermissionError(32, 'sharing violation', str(destination))
            error.winerror = 32
            raise error
        return original_replace(source, destination)

    monkeypatch.setattr(collection.os, 'replace', block_pointer_only)
    with pytest.raises(collection.CollectionPersistenceError):
        collection._persist_collection_manifest(ident, version_dir, updated)
    assert pointer_path.read_text(encoding='utf-8') == original_pointer
    assert json.loads((version_dir / 'manifest.json').read_text(encoding='utf-8')) == initial
    active_dir, active_manifest = collection._active_manifest(ident)
    assert active_dir == version_dir
    assert active_manifest == initial
    pointer = json.loads(original_pointer)
    assert pointer['manifest_sha256'] == collection._sha(version_dir / 'manifest.json')
    assert not list(version_dir.glob('*.tmp'))


def test_persistence_failure_does_not_complete_evidence_stage(collection_case, monkeypatch):
    ident, _, _, _ = collection_case
    pointer_path = collection._active_path(ident)
    monkeypatch.setattr(collection.time, 'sleep', lambda _: None)

    def block_pointer_only(source, destination):
        if Path(destination) == pointer_path:
            error = PermissionError(5, 'access denied', str(destination))
            error.winerror = 5
            raise error
        return original_replace(source, destination)

    original_replace = collection.os.replace
    monkeypatch.setattr(collection.os, 'replace', block_pointer_only)
    with pytest.raises(collection.CollectionPersistenceError):
        collection.execute_collection(ident, collectors=[], executors={})
    state = workflow.get_state(ident)
    assert state['stages']['evidence_collection']['status'] != 'completed'


def test_missing_dataforseo_credentials_are_failed_without_transmission(collection_case, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from collectors import dataforseo_client
    ident, _, _, _ = collection_case
    monkeypatch.setattr(dataforseo_client, 'ROOT', tmp_path)
    monkeypatch.delenv('DATAFORSEO_LOGIN', raising=False)
    monkeypatch.delenv('DATAFORSEO_PASSWORD', raising=False)
    monkeypatch.setattr(dataforseo_client, 'settings', SimpleNamespace(dataforseo_login='', dataforseo_password=''))
    transmissions = []
    monkeypatch.setattr(dataforseo_client.requests, 'request', lambda *a, **k: transmissions.append((a, k)))
    result = collection.execute_collection(ident, collectors=['dataforseo'], authorize_paid_dataforseo=True)
    assert result['status'] == 'failed'
    assert transmissions == []
    status = collection.collection_status(ident)
    assert status['summary']['failed'] == 1 and status['summary']['pending'] == 7
    assert status['summary']['skipped'] == 4
    item = next(row for row in status['items'] if row['status'] == 'failed')
    assert 'Missing DataForSEO credentials' in item['error']
    assert item['transmission_status'] == 'not_sent'
    assert status['statistics']['operation_attempts'] == 1
    assert status['statistics']['dataforseo_transmission_attempts'] == 0
    assert status['statistics']['dataforseo_http_responses_received'] == 0
    assert status['request_accounting']['legacy_paid_requests_made'] == 0


def test_real_dataforseo_transport_events_are_accounted_with_mocked_http(collection_case, monkeypatch):
    from types import SimpleNamespace
    from collectors import dataforseo_client, request_cache
    ident, _, selection, root = collection_case
    monkeypatch.setattr(dataforseo_client, 'ROOT', root)
    monkeypatch.delenv('DATAFORSEO_LOGIN', raising=False)
    monkeypatch.delenv('DATAFORSEO_PASSWORD', raising=False)
    monkeypatch.setattr(dataforseo_client, 'settings', SimpleNamespace(dataforseo_login='test-login', dataforseo_password='test-password'))
    monkeypatch.setattr(request_cache, 'CACHE_DIR', root / 'request-cache')
    items = collection._items(selection)
    by_payload = {json.dumps(item['payload'], sort_keys=True): item for item in items if item['collector'] == 'dataforseo'}
    transmissions = []
    class Response:
        status_code = 200
        def __init__(self, body): self.body = body
        def raise_for_status(self): return None
        def json(self): return self.body
    def fake_request(method, url, *, auth, json, headers, timeout):
        transmissions.append((method, url))
        item = by_payload[json_module.dumps(json, sort_keys=True)]
        body = _mock_for(item, [False], [])
        return Response(body)
    import json as json_module
    monkeypatch.setattr(dataforseo_client.requests, 'request', fake_request)
    calls = []
    result = collection.execute_collection(ident, collectors=['dataforseo'], authorize_paid_dataforseo=True,
        executors={'playwright': lambda item: _mock_for(item, [False], calls),
                   'lighthouse': lambda item: _mock_for(item, [False], calls)})
    assert len(transmissions) == 8
    assert result['statistics']['operation_attempts'] == 8
    assert result['statistics']['dataforseo_transmission_attempts'] == 8
    assert result['statistics']['dataforseo_http_responses_received'] == 8
    assert result['statistics']['api_confirmed_charge_records'] == 8
    assert result['statistics']['api_confirmed_charges_usd'] == pytest.approx(0.08)
    assert result['status'] == 'awaiting_review'
    row = next(item for item in collection.collection_status(ident)['items'] if item['collector'] == 'dataforseo')
    assert row['http_status'] == 200 and row['api_status'] == 20000


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

