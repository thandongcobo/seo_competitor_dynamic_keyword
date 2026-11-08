"""Offline saved-SERP selection and orchestration tests; no live collectors."""
import hashlib
import json
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import Request, urlopen

import pytest

from scripts import dashboard_serp_search, hollywoodbets_comparisons as comparisons
from scripts import investigation_workflow, serp_investigations
from scripts.serve_dashboard import Handler


def _snapshot(keyword='synthetic garden lights'):
    rows = [
        {'rank_group': 1, 'domain': 'betway.co.za', 'title': 'Competitor page', 'url': 'https://betway.co.za/garden-lights?src=serp'},
        {'rank_group': 2, 'domain': 'hollywoodbets.net', 'title': 'Hollywood page', 'url': 'https://www.hollywoodbets.net/garden-lights'},
        {'rank_group': 3, 'domain': 'third.example', 'title': 'Third-party page', 'url': 'https://third.example/solar'},
        {'rank_group': 4, 'domain': 'www.hollywoodbets.net', 'title': 'Second Hollywood page', 'url': 'https://www.hollywoodbets.net/garden-lights/guide'},
        {'rank_group': 5, 'domain': 'fakehollywoodbets.example', 'title': 'Suffix collision', 'url': 'https://fakehollywoodbets.example/page'},
    ]
    return {'keyword': keyword, 'status': 'ok', 'datetime': '2026-10-21T10:48:14+00:00',
        'collection_method': 'playwright_local_browser', 'search_url': f'https://www.google.com/search?q={keyword}',
        'location_note': 'Synthetic ZA context', 'depth_requested': 10, 'depth_collected': len(rows),
        'pages_completed': 1, 'stop_reason': 'minimum_depth_reached', 'maximum_search_depth': 100,
        'tracked_site': {'domain':'hollywoodbets.net','status':'found','rank':2,
            'ranking_url':rows[1]['url'],'ranking_title':rows[1]['title'],
            'results_above':1,'results_below':3,'complete':True},
        'organic_results':rows}


@pytest.fixture
def phase2_case(tmp_path, monkeypatch):
    root = tmp_path / 'engine'
    investigations = root / 'data' / 'investigations'
    snapshot_path = root / 'data' / 'raw' / 'serp' / 'synthetic_garden_lights_google_playwright.json'
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps(_snapshot()), encoding='utf-8')
    root.mkdir(exist_ok=True)
    monkeypatch.setattr(dashboard_serp_search, '_snapshot_path', lambda keyword: snapshot_path)
    monkeypatch.setattr(comparisons, 'ROOT', root)
    monkeypatch.setattr(comparisons, 'INVESTIGATIONS', investigations)
    monkeypatch.setattr(comparisons, '_IDEMPOTENCY_DIR', root / 'data' / 'investigation_workflows' / 'idempotency')
    monkeypatch.setattr(comparisons, '_LOCK_PATH', root / 'data' / 'investigation_workflows' / 'compare.lock')
    monkeypatch.setattr(serp_investigations, 'INVESTIGATIONS', investigations)
    monkeypatch.setattr(investigation_workflow, 'ROOT', root)
    return root, investigations, snapshot_path


def _create(options, key='compare_request_key_00000001', primary=None, competitor=None, parent=None):
    return comparisons.create_comparison(keyword=options['keyword'],
        snapshot_sha256=options['snapshot_sha256'],
        primary_url=primary or options['default_primary_url'],
        competitor_url=competitor or options['competitor_options'][0]['url'],
        idempotency_key=key, parent_investigation_id=parent)


def test_default_primary_is_existing_highest_hollywoodbets_result(phase2_case):
    options = comparisons.selection_options('synthetic garden lights')
    assert options['status'] == 'ready'
    assert options['default_primary_url'] == 'https://www.hollywoodbets.net/garden-lights'
    assert options['primary_options'][0]['rank'] == 2
    assert [row['rank'] for row in options['primary_options']] == [2, 4]
    assert all(not row['is_hollywoodbets'] for row in options['competitor_options'])
    assert any(row['domain'] == 'fakehollywoodbets.example' for row in options['competitor_options'])


def test_compare_persists_exact_serp_context_and_is_idempotent(phase2_case):
    _, investigations, _ = phase2_case
    options = comparisons.selection_options('synthetic garden lights')
    selected_competitor = options['competitor_options'][0]
    first = _create(options, competitor=selected_competitor['url'])
    selection = first['investigation']
    assert first['created'] and not first['idempotent_replay']
    assert selection['selection_origin'] == 'saved_google_serp_snapshot'
    assert selection['serp_sha256'] == options['snapshot_sha256']
    assert selection['serp_snapshot_reference'] == options['snapshot_reference']
    assert selection['source'] == 'observed_google_playwright_serp'
    assert selection['selection_method'] == 'hollywoodbets_first_saved_serp'
    assert selection['search_context']['location_note'] == 'Synthetic ZA context'
    assert selection['ours']['rank'] == 2 and selection['ours']['url'] == options['default_primary_url']
    assert selection['benchmark']['rank'] == selected_competitor['rank']
    assert selection['benchmark']['url'] == selected_competitor['url']
    assert selection['ours']['redirect_url'] is None and selection['ours']['canonical_url'] is None
    assert first['workflow']['current_stage'] == 'webpage_selection'
    assert first['collection_plan']['summary']['required_items'] == 12
    assert first['collection_plan']['summary']['dataforseo_paid_requests'] == 8
    assert first['collection_plan']['summary']['playwright_top_level_captures'] == 2
    assert first['collection_plan']['summary']['lighthouse_runs'] == 2
    again = _create(options, competitor=selected_competitor['url'])
    assert again['idempotent_replay'] and not again['created']
    assert again['investigation']['investigation_id'] == selection['investigation_id']
    records = list(investigations.glob('*/selection.json'))
    assert len(records) == 1


def test_rejects_fabricated_self_and_stale_snapshot_selections(phase2_case):
    options = comparisons.selection_options('synthetic garden lights')
    args = {'keyword':options['keyword'],'snapshot_sha256':options['snapshot_sha256'],
        'primary_url':options['default_primary_url'],'idempotency_key':'compare_request_key_00000002'}
    with pytest.raises(ValueError, match='non-Hollywoodbets'):
        comparisons.create_comparison(**args, competitor_url=options['primary_options'][0]['url'])
    with pytest.raises(ValueError, match='same saved SERP'):
        comparisons.create_comparison(**args, competitor_url='https://invented.example/not-ranked')
    with pytest.raises(ValueError, match='changed'):
        comparisons.create_comparison(**{**args,'snapshot_sha256':'0'*64},
            competitor_url=options['competitor_options'][0]['url'])


def test_absent_or_inconsistent_hollywoodbets_is_not_guessed(phase2_case):
    _, _, path = phase2_case
    snapshot = _snapshot()
    snapshot['organic_results'] = [row for row in snapshot['organic_results'] if 'hollywoodbets.net' not in row['domain']]
    snapshot['tracked_site'].update(status='not_found', rank=None, ranking_url=None)
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    absent = comparisons.selection_options('synthetic garden lights')
    assert absent['status'] == 'hollywoodbets_not_found'
    assert absent['message'] == comparisons.HOLLYWOODBETS_NOT_FOUND
    snapshot = _snapshot()
    snapshot['tracked_site']['ranking_url'] = 'https://hollywoodbets.net/fabricated'
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    invalid = comparisons.selection_options('synthetic garden lights')
    assert invalid['status'] == 'selection_error'
    assert 'conflicts' in invalid['message']


def test_competitor_change_creates_child_branch_without_mutating_parent(phase2_case):
    _, investigations, _ = phase2_case
    options = comparisons.selection_options('synthetic garden lights')
    parent = _create(options, key='compare_request_key_parent01')
    parent_id = parent['investigation']['investigation_id']
    parent_bytes = (investigations / parent_id / 'selection.json').read_bytes()
    new_competitor = next(row for row in options['competitor_options'] if row['domain'] == 'third.example')
    child = _create(options, key='compare_request_key_child0001', competitor=new_competitor['url'], parent=parent_id)
    assert child['investigation']['parent_investigation_id'] == parent_id
    assert child['investigation']['ours']['url'] == parent['investigation']['ours']['url']
    assert child['investigation']['benchmark']['url'] == new_competitor['url']
    assert child['workflow']['current_stage'] == 'webpage_selection'
    assert (investigations / parent_id / 'selection.json').read_bytes() == parent_bytes
    assert (investigations / child['investigation']['investigation_id'] / 'workflow_branch.json').is_file()


@pytest.mark.parametrize('keyword,primary_url,competitor_url', [
    ('organic cat food', 'https://www.hollywoodbets.net/cat-food', 'https://example-one.test/cat-food'),
    ('compact espresso grinder', 'https://www.hollywoodbets.net/grinders/compact', 'https://example-two.test/grinders/compact'),
])
def test_unrelated_keywords_use_only_their_own_saved_snapshot(phase2_case, monkeypatch,
        keyword, primary_url, competitor_url):
    root, _, _ = phase2_case
    path = root / 'data' / 'raw' / 'serp' / f'{keyword.replace(" ", "_")}.json'
    rows = [
        {'rank_group':1,'domain':'hollywoodbets.net','title':'Primary','url':primary_url},
        {'rank_group':2,'domain':'example.test','title':'Competitor','url':competitor_url},
    ]
    data = _snapshot(keyword)
    data.update(organic_results=rows)
    data['tracked_site'].update(rank=1,ranking_url=primary_url,ranking_title='Primary',results_above=0,results_below=1)
    path.write_text(json.dumps(data),encoding='utf-8')
    monkeypatch.setattr(dashboard_serp_search,'_snapshot_path',lambda requested: path if requested==keyword else root/'missing.json')
    options=comparisons.selection_options(keyword)
    assert options['default_primary_url']==primary_url
    result=_create(options,key=('keyword_'+str(abs(hash(keyword)))+'_compare_0001')[:80],competitor=competitor_url)
    assert result['investigation']['keyword']==keyword
    assert result['investigation']['benchmark']['url']==competitor_url


def test_http_saved_selection_endpoint_and_compare_idempotency(phase2_case):
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/api/serp/hollywoodbets-options?keyword=synthetic%20garden%20lights') as response:
            options=json.load(response)
        payload={'keyword':options['keyword'],'snapshot_sha256':options['snapshot_sha256'],
            'primary_url':options['default_primary_url'],'competitor_url':options['competitor_options'][0]['url'],
            'idempotency_key':'http_compare_request_key_0001'}
        req=Request(base+'/api/investigations/hollywoodbets-compare',json.dumps(payload).encode(),
            {'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response:
            assert response.status==201
            first=json.load(response)
        req=Request(base+'/api/investigations/hollywoodbets-compare',json.dumps(payload).encode(),
            {'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response:
            assert response.status==200
            replay=json.load(response)
        assert replay['idempotent_replay']
        with urlopen(base+f"/api/investigations/{first['investigation']['investigation_id']}/workflow") as response:
            assert json.load(response)['current_stage']=='webpage_selection'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)


def test_simultaneous_compare_retries_create_only_one_investigation(phase2_case):
    _, investigations, _ = phase2_case
    options = comparisons.selection_options('synthetic garden lights')
    kwargs = {'keyword':options['keyword'],'snapshot_sha256':options['snapshot_sha256'],
        'primary_url':options['default_primary_url'],
        'competitor_url':options['competitor_options'][0]['url'],
        'idempotency_key':'simultaneous_compare_request_001'}
    results=[]; errors=[]
    def compare():
        try: results.append(comparisons.create_comparison(**kwargs))
        except Exception as exc: errors.append(exc)
    threads=[Thread(target=compare) for _ in range(5)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=10)
    assert not errors
    assert len(results)==5
    assert len({item['investigation']['investigation_id'] for item in results})==1
    assert sum(not item['idempotent_replay'] for item in results)==1
    assert len(list(investigations.glob('*/selection.json')))==1
