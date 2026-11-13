import json
import threading
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts import investigation_workflow as workflow
from scripts import serp_investigations


@pytest.fixture
def investigation(tmp_path, monkeypatch):
    root = tmp_path / 'investigations'
    ident = 'a' * 32
    folder = root / ident
    folder.mkdir(parents=True)
    selection = {
        'schema_version': '1.1', 'investigation_id': ident, 'keyword': 'synthetic running shoes',
        'serp_sha256': None, 'serp_collected_at': None, 'source': 'manual_exact_webpage_urls',
        'ours': {'domain': 'trail.example', 'url': 'https://trail.example/shoes'},
        'benchmark': {'domain': 'track.example', 'url': 'https://track.example/running'},
    }
    (folder / 'selection.json').write_text(json.dumps(selection), encoding='utf-8')
    monkeypatch.setattr(serp_investigations, 'INVESTIGATIONS', root)
    return ident, folder, selection


def test_sequential_checkpoint_navigation_and_restart(investigation, monkeypatch):
    ident, folder, _ = investigation
    monkeypatch.setattr('scripts.investigation_offline.evidence_inventory', lambda selection: {
        'complete': True, 'required_evidence_items': 0, 'entries': [], 'requests_made': 0
    })
    state = workflow.get_state(ident)
    assert state['current_stage'] == 'webpage_selection'
    assert state['stages']['keyword_search']['status'] == 'completed'
    with pytest.raises(ValueError, match='prerequisites'):
        workflow.execute_stage(ident, 'evidence_processing')
    workflow.execute_stage(ident, 'webpage_selection')
    state = workflow.navigate(ident, 'next')
    assert state['current_stage'] == 'evidence_collection'
    state = workflow.execute_stage(ident, 'evidence_collection')
    stage = state['stages']['evidence_collection']
    assert stage['status'] == 'awaiting_review'
    assert stage['error']['kind'] == 'evidence_missing'
    manifest_path = folder / 'workflow' / 'collections' / stage['collection_version'] / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['status'] == 'awaiting_review'
    assert len(manifest['items']) == 12
    # Generic workflow inventory is read-only and does not select collectors.
    assert all(row['status'] == 'skipped' for row in manifest['items'].values())
    reused = workflow.execute_stage(ident, 'evidence_collection')
    assert reused['stages']['evidence_collection']['status'] == 'awaiting_review'
    assert reused['stages']['evidence_collection']['cache'] != 'hit'
    assert reused['stages']['evidence_collection']['request_summary']['paid_requests_made'] == 0
    assert reused['stages']['evidence_collection']['request_summary']['playwright_top_level_captures'] == 0
    reloaded = workflow.get_state(ident)
    assert reloaded['completed_stages'] == ['keyword_search', 'webpage_selection']
    assert (folder / 'workflow' / 'checkpoint.json').is_file()


def test_missing_evidence_waits_for_review_and_does_not_advance(investigation, monkeypatch):
    ident, _, _ = investigation
    monkeypatch.setattr('scripts.investigation_offline.evidence_inventory', lambda selection: {
        'complete': False, 'required_evidence_items': 1, 'entries': [{'status': 'missing'}], 'requests_made': 0
    })
    workflow.execute_stage(ident, 'keyword_search')
    workflow.execute_stage(ident, 'webpage_selection')
    state = workflow.execute_stage(ident, 'evidence_collection')
    assert state['stages']['evidence_collection']['status'] == 'awaiting_review'
    with pytest.raises(ValueError, match='prerequisites'):
        workflow.execute_stage(ident, 'evidence_processing')


def test_interrupted_stage_is_recovered_after_restart(investigation):
    ident, _, _ = investigation
    state = workflow.get_state(ident)
    state['stages']['keyword_search']['status'] = 'running'
    workflow._write_state(ident, state)
    recovered = workflow.get_state(ident)
    assert recovered['stages']['keyword_search']['status'] == 'failed'
    assert recovered['stages']['keyword_search']['error']['kind'] == 'server_restart'


def test_completed_checkpoint_with_changed_artifact_is_not_reused(investigation):
    ident, folder, _ = investigation
    selection_file = folder / 'selection.json'
    stage = workflow.get_state(ident)
    stage['stages']['webpage_selection'].update(status='completed', outputs=[
        {'path': 'selection.json', 'sha256': '0' * 64}
    ])
    workflow._write_state(ident, stage)
    resumed = workflow.get_state(ident)
    assert resumed['stages']['webpage_selection']['status'] == 'failed'
    assert resumed['stages']['webpage_selection']['error']['kind'] == 'checkpoint_integrity_failure'
    assert selection_file.is_file()


def test_recovered_report_outputs_pin_execution_record(investigation):
    _, folder, _ = investigation
    comparison = folder / 'results' / 'comparison.json'
    comparison.parent.mkdir(parents=True)
    comparison.write_text('{"recommendations":[]}', encoding='utf-8')
    execution = folder / 'offline_execution.json'
    execution.write_text(json.dumps({'status':'completed'}), encoding='utf-8')
    outputs = workflow._verified_report_outputs(folder, {
        'comparison_path': 'results/comparison.json',
    })
    by_path = {row['path']: row for row in outputs}
    assert by_path['offline_execution.json']['sha256'] == workflow._sha(execution)
    assert by_path['offline_execution.json']['size_bytes'] == execution.stat().st_size


def test_failed_attempt_is_not_cached_as_success_and_can_retry(investigation, monkeypatch):
    ident, _, _ = investigation
    calls = {'count': 0}

    def inventory(_selection):
        calls['count'] += 1
        if calls['count'] == 1:
            raise RuntimeError('fixture collection failure')
        return {'complete': True, 'required_evidence_items': 0, 'entries': [], 'requests_made': 0}

    monkeypatch.setattr('scripts.investigation_offline.evidence_inventory', inventory)
    workflow.execute_stage(ident, 'keyword_search')
    workflow.execute_stage(ident, 'webpage_selection')
    with pytest.raises(RuntimeError, match='fixture collection failure'):
        workflow.execute_stage(ident, 'evidence_collection')
    state = workflow.get_state(ident)
    assert state['stages']['evidence_collection']['status'] == 'failed'
    state = workflow.execute_stage(ident, 'evidence_collection')
    stage = state['stages']['evidence_collection']
    assert stage['status'] == 'awaiting_review'
    assert stage['error']['kind'] == 'evidence_missing'
    assert stage['request_summary']['paid_requests_made'] == 0
    assert len(state['stages']['evidence_collection']['attempts']) == 2


def test_lock_serializes_concurrent_stage_requests(investigation, monkeypatch):
    ident, _, _ = investigation
    monkeypatch.setattr('scripts.investigation_offline.evidence_inventory', lambda selection: {
        'complete': True, 'required_evidence_items': 0, 'entries': [], 'requests_made': 0
    })
    workflow.execute_stage(ident, 'keyword_search')
    workflow.execute_stage(ident, 'webpage_selection')
    errors = []

    def run():
        try:
            workflow.execute_stage(ident, 'evidence_collection')
        except Exception as exc:
            errors.append(exc)

    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert not errors
    state = workflow.get_state(ident)
    stage = state['stages']['evidence_collection']
    assert stage['status'] == 'awaiting_review'
    assert stage['error']['kind'] == 'evidence_missing'
    assert len(stage['attempts']) == 2
    assert stage['request_summary']['paid_requests_made'] == 0
    assert stage['request_summary']['playwright_top_level_captures'] == 0


def test_competitor_change_creates_child_without_mutating_parent(investigation):
    ident, folder, selection = investigation
    before = (folder / 'selection.json').read_bytes()
    result = workflow.branch_competitor(ident, 'https://pace.example/track')
    child_id = result['investigation']['investigation_id']
    child = serp_investigations.read_investigation(child_id)
    assert child['ours']['url'] == selection['ours']['url']
    assert child['benchmark']['url'] == 'https://pace.example/track'
    assert result['branch']['parent_investigation_id'] == ident
    assert (folder / 'selection.json').read_bytes() == before


def test_cache_fingerprint_separates_contexts():
    a = {'keyword': 'running shoes', 'ours': {'url': 'https://a.example/one'}}
    b = {'keyword': 'tennis shoes', 'ours': {'url': 'https://a.example/one'}}
    assert workflow._input_digest('evidence_collection', a) != workflow._input_digest('evidence_collection', b)


def test_keyword_search_job_is_persisted_without_credentials(tmp_path, monkeypatch):
    from scripts import dashboard_serp_search
    monkeypatch.setattr(workflow, '_search_jobs_dir', lambda: tmp_path)
    monkeypatch.setattr(dashboard_serp_search, 'start_search', lambda keyword, depth: {
        'job_id': 'b' * 32, 'keyword': keyword, 'depth': depth, 'status': 'running',
        'started_at': '2026-01-01T00:00:00+00:00', 'finished_at': None
    })
    monkeypatch.setattr(dashboard_serp_search, 'job_status', lambda job_id: None)
    started = workflow.start_keyword_search('running shoes', 10)
    saved = json.loads((tmp_path / f"{started['job_id']}.json").read_text(encoding='utf-8'))
    assert saved['fingerprint']
    assert saved['request']['keyword'] == 'running shoes'
    assert 'credentials_stored' in saved and saved['credentials_stored'] is False
    assert not any('password' in key.lower() or 'login' in key.lower() for key in saved['request']['configuration'])
    resumed = workflow.keyword_search_status(started['job_id'])
    assert resumed['status'] == 'failed'


def test_search_job_reconciles_verified_snapshot_after_restart(tmp_path, monkeypatch):
    from scripts import dashboard_serp_search
    jobs = tmp_path / 'jobs'
    jobs.mkdir()
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text('{"saved":true}', encoding='utf-8')
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    monkeypatch.setattr(workflow, '_search_jobs_dir', lambda: jobs)
    monkeypatch.setattr(dashboard_serp_search, 'start_search', lambda keyword, depth: {
        'job_id': 'c' * 32, 'keyword': keyword, 'depth': depth, 'status': 'running',
        'started_at': '2026-01-01T00:00:00+00:00', 'finished_at': None
    })
    monkeypatch.setattr(dashboard_serp_search, 'job_status', lambda job_id: None)
    monkeypatch.setattr(dashboard_serp_search, '_snapshot_path', lambda keyword: snapshot)
    monkeypatch.setattr(dashboard_serp_search, 'read_snapshot', lambda keyword: {
        'keyword': keyword, 'collected_at': '2026-02-01T00:00:00+00:00', 'organic_results': []
    })
    started = workflow.start_keyword_search('offline synthetic query', 10)
    resumed = workflow.keyword_search_status(started['job_id'])
    assert resumed['status'] == 'completed'
    assert resumed['result']['keyword'] == 'offline synthetic query'
    assert resumed['snapshot']['sha256']


def test_dashboard_workflow_api_reads_and_executes_only_explicit_stage(investigation):
    from scripts.serve_dashboard import Handler
    ident, _, _ = investigation
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(f'{base}/api/investigations/{ident}/workflow') as response:
            initial = json.load(response)
        assert initial['stages']['keyword_search']['status'] == 'completed'
        request = Request(f'{base}/api/investigations/{ident}/workflow/execute',
                          json.dumps({'stage': 'webpage_selection'}).encode(),
                          {'Content-Type': 'application/json'}, method='POST')
        with urlopen(request) as response:
            updated = json.load(response)
        assert updated['stages']['webpage_selection']['status'] == 'completed'
        with urlopen(f'{base}/api/investigations/{ident}/workflow') as response:
            reopened = json.load(response)
        assert reopened['completed_stages'] == ['keyword_search', 'webpage_selection']
        request = Request(f'{base}/api/investigations/{ident}/workflow/execute',
                          json.dumps({'stage': 'evidence_processing'}).encode(),
                          {'Content-Type': 'application/json'}, method='POST')
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

