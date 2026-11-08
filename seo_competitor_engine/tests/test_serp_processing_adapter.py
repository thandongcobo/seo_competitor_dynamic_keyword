"""Offline verification of the saved-SERP processor source contract."""
import hashlib
import json
from pathlib import Path

import pytest

from config.settings import keyword_slug
from scripts import dashboard_serp_search, hollywoodbets_comparisons as comparisons
from scripts import investigation_offline, investigation_workflow, serp_investigations
from scripts import run_investigation_offline, serp_processing_adapter as adapter


def _snapshot(keyword):
    rows = [
        {'rank_group': 1, 'domain': 'betway.co.za', 'title': 'Observed competitor',
         'url': f'https://www.betway.co.za/{keyword.replace(" ", "-")}'},
        {'rank_group': 2, 'domain': 'hollywoodbets.net', 'title': 'Observed Hollywoodbets page',
         'url': f'https://www.hollywoodbets.net/{keyword.replace(" ", "-")}'},
        {'rank_group': 3, 'domain': 'independent.example', 'title': 'Other observed result',
         'url': f'https://independent.example/{keyword.replace(" ", "-")}'},
        {'rank_group': 4, 'domain': 'www.hollywoodbets.net', 'title': 'Second Hollywoodbets page',
         'url': f'https://www.hollywoodbets.net/{keyword.replace(" ", "-")}/guide'},
    ]
    return {'keyword': keyword, 'status': 'ok', 'datetime': '2026-10-21T10:48:14.108486+00:00',
        'collection_method': 'playwright_local_browser',
        'search_url': f'https://www.google.com/search?q={keyword.replace(" ", "+")}',
        'location_note': 'Synthetic ZA test context', 'depth_requested': 10,
        'depth_collected': len(rows), 'pages_completed': 1,
        'stop_reason': 'tracked_site_found_with_neighbours', 'maximum_search_depth': 100,
        'tracked_site': {'domain':'hollywoodbets.net','status':'found','rank':2,
            'ranking_url':rows[1]['url'],'ranking_title':rows[1]['title'],
            'results_above':1,'results_below':2,'complete':True},
        'organic_results': rows}


@pytest.fixture

def valid_serp_investigation(tmp_path, monkeypatch):
    root = tmp_path / 'engine'
    root.mkdir()
    inv_root = root / 'data' / 'investigations'
    idem_root = root / 'data' / 'investigation_workflows' / 'hollywoodbets_compare_requests'
    snapshot_path = root / 'data' / 'raw' / 'serp' / f'{keyword_slug("garden solar")}_google_playwright.json'
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps(_snapshot('garden solar')), encoding='utf-8')
    monkeypatch.setattr(dashboard_serp_search, '_snapshot_path', lambda keyword: snapshot_path)
    monkeypatch.setattr(serp_investigations, '_snapshot_path', lambda keyword: snapshot_path)
    monkeypatch.setattr(comparisons, 'ROOT', root)
    monkeypatch.setattr(comparisons, 'INVESTIGATIONS', inv_root)
    monkeypatch.setattr(comparisons, '_IDEMPOTENCY_DIR', idem_root)
    monkeypatch.setattr(comparisons, '_LOCK_PATH', root / 'data' / 'investigation_workflows' / 'compare.lock')
    monkeypatch.setattr(serp_investigations, 'INVESTIGATIONS', inv_root)
    monkeypatch.setattr(investigation_workflow, 'ROOT', root)
    monkeypatch.setattr(investigation_offline, 'ROOT', root)
    monkeypatch.setattr(adapter, 'ROOT', root)
    monkeypatch.setattr(adapter, 'IDEMPOTENCY_DIR', idem_root)
    options = comparisons.selection_options('garden solar')
    selected = comparisons.create_comparison(keyword='garden solar',
        snapshot_sha256=options['snapshot_sha256'], primary_url=options['default_primary_url'],
        competitor_url=options['competitor_options'][0]['url'],
        idempotency_key='serp_adapter_request_key_001')
    investigation_id = selected['investigation']['investigation_id']
    investigation_workflow.execute_stage(investigation_id, 'keyword_search')
    investigation_workflow.execute_stage(investigation_id, 'webpage_selection')
    return {'root':root, 'snapshot_path':snapshot_path, 'investigation_id':investigation_id,
            'selection_path':inv_root/investigation_id/'selection.json', 'idem_root':idem_root,
            'inv_root':inv_root, 'options':options, 'result':selected}


def _refresh_selection_checkpoint(case):
    path = case['inv_root']/case['investigation_id']/'workflow'/'checkpoint.json'
    state = json.loads(path.read_text(encoding='utf-8'))
    output = state['stages']['webpage_selection']['outputs'][0]
    output['sha256'] = hashlib.sha256(case['selection_path'].read_bytes()).hexdigest()
    output['size_bytes'] = case['selection_path'].stat().st_size
    path.write_text(json.dumps(state, indent=2), encoding='utf-8')


def _mutate_selection(case, change):
    selection = json.loads(case['selection_path'].read_text(encoding='utf-8'))
    change(selection)
    case['selection_path'].write_text(json.dumps(selection, indent=2), encoding='utf-8')
    _refresh_selection_checkpoint(case)


def test_valid_saved_serp_contract_checks_exact_urls_ranks_context_and_id(valid_serp_investigation):
    case = valid_serp_investigation
    selection = adapter.validate_serp_origin_investigation(case['investigation_id'])
    assert selection['source'] == 'observed_google_playwright_serp'
    assert selection['keyword'] == 'garden solar'
    assert selection['ours']['url'] == case['options']['default_primary_url']
    assert selection['ours']['rank'] == 2
    assert selection['benchmark']['url'] == case['options']['competitor_options'][0]['url']
    assert selection['benchmark']['rank'] == 1
    assert selection['serp_sha256'] == case['options']['snapshot_sha256']


@pytest.mark.parametrize('keyword,ours_path,competitor_path', [
    ('organic cat food', 'cat-food', 'example-one.test/cat-food'),
    ('compact espresso grinder', 'grinders/compact', 'example-two.test/grinders/compact'),
])
def test_two_unrelated_synthetic_keyword_contracts(keyword, ours_path, competitor_path, tmp_path, monkeypatch):
    case = valid_serp_investigation.__wrapped__(tmp_path, monkeypatch)
    # Rebind the fixture's saved snapshot to a different, unrelated keyword and page pair.
    root = case['root']; inv_root = case['inv_root']
    old_id = case['investigation_id']
    # Existing helper is keyword-specific, so create an independent snapshot and fresh root state.
    snapshot_path = root/'data'/'raw'/'serp'/f'{keyword_slug(keyword)}_google_playwright.json'
    snapshot = _snapshot(keyword)
    snapshot['organic_results'][1]['url'] = f'https://www.hollywoodbets.net/{ours_path}'
    snapshot['tracked_site']['ranking_url'] = snapshot['organic_results'][1]['url']
    snapshot['organic_results'][0]['url'] = f'https://{competitor_path}'
    snapshot['organic_results'][0]['domain'] = competitor_path.split('/')[0]
    snapshot['search_url'] = f'https://www.google.com/search?q={keyword.replace(" ", "+")}'
    snapshot_path.write_text(json.dumps(snapshot),encoding='utf-8')
    dashboard_serp_search._snapshot_path = lambda query: snapshot_path if query.casefold()==keyword.casefold() else case['snapshot_path']
    case['snapshot_path']=snapshot_path
    case['options']=comparisons.selection_options(keyword)
    case['result']=comparisons.create_comparison(keyword=keyword,
        snapshot_sha256=case['options']['snapshot_sha256'],primary_url=case['options']['default_primary_url'],
        competitor_url=case['options']['competitor_options'][0]['url'],
        idempotency_key='serp_adapter_synthetic_key_002')
    case['investigation_id']=case['result']['investigation']['investigation_id']
    case['selection_path']=inv_root/case['investigation_id']/'selection.json'
    investigation_workflow.execute_stage(case['investigation_id'],'keyword_search')
    investigation_workflow.execute_stage(case['investigation_id'],'webpage_selection')
    verified=adapter.validate_serp_origin_investigation(case['investigation_id'])
    assert verified['keyword']==keyword
    assert verified['ours']['url']==f'https://www.hollywoodbets.net/{ours_path}'
    assert verified['benchmark']['url']==f'https://{competitor_path}'
    assert verified['source']=='observed_google_playwright_serp'
    assert old_id != case['investigation_id']


@pytest.mark.parametrize('change,expected', [
    (lambda s:s.update(source='wrong_source'), 'source contract'),
    (lambda s:s.update(selection_method='manual'), 'source contract'),
    (lambda s:s.update(selection_origin='manual'), 'source contract'),
    (lambda s:s.update(keyword='mismatched keyword'), 'mismatched or not a successful Google observation'),
    (lambda s:s.update(serp_sha256='0'*64), 'snapshot SHA-256'),
    (lambda s:s.update(serp_snapshot_reference='data/raw/serp/fabricated.json'), 'snapshot reference'),
    (lambda s:s.update(serp_collected_at='2026-10-22T00:00:00+00:00'), 'timestamp'),
    (lambda s:s['search_context'].update(location_note='fabricated'), 'search context'),
    (lambda s:s['hollywoodbets_identification'].update(default_url='https://hollywoodbets.net/fabricated'), 'identification metadata'),
    (lambda s:s['hollywoodbets_identification'].update(default_rank=7), 'identification metadata'),
    (lambda s:s['ours'].update(url='https://hollywoodbets.net/fabricated'), 'exact Hollywoodbets URL'),
    (lambda s:s['ours'].update(rank=8), 'position'),
    (lambda s:s['benchmark'].update(url='https://competitor.example/fabricated'), 'exact competitor URL'),
    (lambda s:s['benchmark'].update(rank=9), 'position'),
    (lambda s:s['benchmark'].update(url='https://www.hollywoodbets.net/garden-solar/guide', rank=4,
                                      domain='www.hollywoodbets.net', result_index=3,
                                      title='Second Hollywoodbets page'), 'another Hollywoodbets'),
])
def test_rejects_tampered_selection_fields(valid_serp_investigation, change, expected):
    case=valid_serp_investigation
    _mutate_selection(case,change)
    with pytest.raises((ValueError,FileNotFoundError),match=expected):
        adapter.validate_serp_origin_investigation(case['investigation_id'])


def test_rejects_modified_snapshot_even_if_saved_file_remains_parseable(valid_serp_investigation):
    case=valid_serp_investigation
    snapshot=json.loads(case['snapshot_path'].read_text(encoding='utf-8'))
    snapshot['location_note']='edited after selection'
    case['snapshot_path'].write_text(json.dumps(snapshot),encoding='utf-8')
    with pytest.raises(ValueError,match='SHA-256'):
        adapter.validate_serp_origin_investigation(case['investigation_id'])


def test_rejects_unknown_id_missing_checkpoint_and_invalid_request_record(valid_serp_investigation):
    case=valid_serp_investigation
    with pytest.raises(FileNotFoundError):
        adapter.validate_serp_origin_investigation('a'*32)
    checkpoint=case['inv_root']/case['investigation_id']/'workflow'/'checkpoint.json'
    original=checkpoint.read_bytes(); checkpoint.unlink()
    with pytest.raises(ValueError,match='checkpoint'):
        adapter.validate_serp_origin_investigation(case['investigation_id'])
    checkpoint.write_bytes(original)
    record_path=next(case['idem_root'].glob('*.json'))
    record=json.loads(record_path.read_text(encoding='utf-8')); record['request_fingerprint']='0'*64
    record_path.write_text(json.dumps(record),encoding='utf-8')
    with pytest.raises(ValueError,match='request record'):
        adapter.validate_serp_origin_investigation(case['investigation_id'])


def test_runner_rejects_incomplete_evidence_after_valid_serp_contract(valid_serp_investigation):
    case=valid_serp_investigation
    selection=adapter.validate_serp_origin_investigation(case['investigation_id'])
    assert selection['source']=='observed_google_playwright_serp'
    with pytest.raises(ValueError,match='Saved evidence incomplete or mismatched'):
        run_investigation_offline.run(case['investigation_id'],root=case['root'],
            investigation_dir=case['inv_root']/case['investigation_id'],generate_pdf=False)
    assert not (case['inv_root']/case['investigation_id']/'offline_execution.json').exists()


def test_runner_preserves_per_artifact_sha256_check_after_valid_serp_contract(valid_serp_investigation, monkeypatch):
    case=valid_serp_investigation
    slug=keyword_slug('garden solar')
    processed_serp=case['root']/'data'/'processed'/slug/'serp_google.json'
    processed_serp.parent.mkdir(parents=True)
    saved=json.loads(case['snapshot_path'].read_text(encoding='utf-8'))
    processed_serp.write_text(json.dumps({'keyword':'garden solar',
        'organic_results':saved['organic_results']}),encoding='utf-8')
    artifact=case['root']/'data'/'raw'/'fixture-corrupted-evidence.json'
    artifact.parent.mkdir(parents=True,exist_ok=True)
    artifact.write_text('{"status":"fixture"}',encoding='utf-8')
    fake_inventory={'complete':True,'entries':[{'kind':'labs_ranked_keywords','side':'ours',
        'path':'data/raw/fixture-corrupted-evidence.json','sha256':'0'*64}]}
    monkeypatch.setattr(run_investigation_offline,'evidence_inventory',lambda selection,root:fake_inventory)
    with pytest.raises(ValueError,match='Evidence changed during offline replay'):
        run_investigation_offline.run(case['investigation_id'],root=case['root'],
            investigation_dir=case['inv_root']/case['investigation_id'],generate_pdf=False)
    base=case['inv_root']/case['investigation_id']
    assert not (base/'offline_execution.json').exists()
    assert not (base/'processed').exists()
    assert not (base/'results').exists()


def test_manual_source_contract_reaches_existing_evidence_validation(valid_serp_investigation):
    case=valid_serp_investigation
    manifest=serp_investigations.create_page_investigation('garden solar',
        'https://manual-primary.example/page','https://manual-competitor.example/page',
        case['options']['snapshot_sha256'])
    with pytest.raises(ValueError,match='Saved evidence incomplete or mismatched'):
        run_investigation_offline.run(manifest['investigation_id'],root=case['root'],
            investigation_dir=case['inv_root']/manifest['investigation_id'],generate_pdf=False)
    assert manifest['source']=='manual_exact_webpage_urls'
