import copy
import json
import tempfile
from pathlib import Path

import pytest
from monitoring import store
from monitoring.activity import activity_feed
from monitoring.diff import compare
from monitoring.intelligence import classify, enrich, verify, summarize_change
from monitoring.promotions import extract_offer_details, investigate_candidates


def test_multiple_labels_and_image_only_unknown():
    result = classify({'extracted_text':'Welcome! Get 5% cash back on crash games.'})
    assert set(result['categories']) == {'welcome','cashback','games'}
    assert classify({'title':'free-bet-cashback-banner.jpg','extracted_text':''})['categories'] == ['unclassified']


def offer():
    text = 'Get R100 free bet when you deposit R50.'
    details = extract_offer_details(text)
    return {'extracted_text':text,'page_url':'https://brand.example/promotions',
            'investigation':{'status':'captured','source_url':'https://brand.example/offer','text_excerpt':text,
                'offer_details':details,'terms_page':{'status':'captured','source_url':'https://brand.example/terms',
                    'text_excerpt':text+' New customers only.', 'details':copy.deepcopy(details)}}}


def test_corroboration_requires_separate_consistent_evidence():
    item = offer()
    assert verify(item)['status'] == 'automatically_corroborated'
    item['investigation']['terms_page']['details']['amounts'] = ['R200','R50']
    assert verify(item)['status'] == 'details_available'
    assert 'amounts' in verify(item)['fields_needing_review']
    item = offer()
    del item['investigation']['offer_details']
    assert verify(item)['status'] != 'automatically_corroborated'
    item = offer()
    item['investigation']['terms_page']['source_url'] = 'https://brand.example/offer'
    assert verify(item)['status'] != 'automatically_corroborated'


def test_matching_amounts_from_unrelated_promotions_do_not_verify():
    item = offer()
    item['investigation']['terms_page']['text_excerpt'] = 'Spend R50 and get a R100 voucher for merchandise.'
    assert verify(item)['status'] != 'automatically_corroborated'


def test_dates_and_promotion_hours_are_meaningful_changes():
    changes = compare({'rendered_page_text':'Ends 2026-10-20 at 19:00.'},
                      {'rendered_page_text':'Ends 2026-10-25 at 21:00.'},'old','new','page')
    assert len(changes) == 1
    summary = summarize_change(changes[0])['summary']
    assert '2026-10-25' in summary and '21:00' in summary and '19:00' in summary


@pytest.fixture
def database(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='intelligence-test-',dir=store.ROOT) as folder:
        monkeypatch.setattr(store,'DB_PATH',Path(folder)/'monitor.sqlite3')
        monkeypatch.setattr(store,'ARTIFACT_DIR',Path(folder)/'artifacts')
        store.init_db()
        yield Path(folder)


def seed_snapshot(folder, page, identifier, timestamp, candidate):
    path=folder/(identifier+'.json')
    path.write_text(json.dumps({'tracking_eligible':True,'promotion_analysis':{'candidates':[candidate]}}),encoding='utf8')
    with store.connect() as connection:
        connection.execute('INSERT INTO captures VALUES (?,?,?,?,?,?,?)',(identifier+'capture',page,'success',timestamp,timestamp,None,None))
        connection.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?)',(identifier,page,identifier+'capture',timestamp,'https://brand.example/promotions','test','hash',str(path)))
    store.record_promotions(page,identifier,timestamp,{'text_scan_complete':True,'image_scan_complete':False,'candidates':[candidate]})


def test_identity_continuity_and_original_evidence_and_feed_filters(database):
    page=store.register('https://brand.example/promotions')
    other=store.register('https://other.example/promotions')
    first={'fingerprint':'first','title':'Get 50 free spins','extracted_text':'Get 50 free spins',
           'target_url':'https://brand.example/offer','source_type':'text+image','details':{}}
    seed_snapshot(database,page,'s1','2026-10-19T08:00:00+00:00',first)
    changed={**first,'fingerprint':'asset-rotated','extracted_text':'Get 75 free spins','title':'Get 75 free spins'}
    seed_snapshot(database,page,'s2','2026-10-20T08:00:00+00:00',changed)
    seed_snapshot(database,other,'other','2026-10-20T09:00:00+00:00',first)
    rows=store.promotions_for_page(page)
    assert len(rows)==1 and rows[0]['status']=='current' and rows[0]['missed_captures']==0
    assert rows[0]['first_snapshot_id']=='s1'
    assert rows[0]['history'][0]['previous_snapshot_id']=='s1'
    feed=activity_feed({'domain':'brand.example'})
    assert len(feed['events'])==2
    first_event=next(e for e in feed['events'] if e['kind']=='promotion_new')
    assert first_event['snapshot_id']=='s1' and '50 free spins' in first_event['summary']
    assert all(e['domain']=='brand.example' for e in feed['events'])
    assert activity_feed({'domain':'brand.example','since':'2026-10-20','until':'2026-10-20'})['total']==1
    assert activity_feed({'domain':'brand.example','limit':'1'})['has_more'] is True


def test_investigation_budget_rotates_and_failure_is_isolated():
    candidates=[{'fingerprint':str(i),'confidence':'high','target_url':f'https://brand.example/offer{i}',
                 'extracted_text':'Get 50 free spins'} for i in range(4)]
    calls=[]
    def fetch(url, **kwargs):
        calls.append(url)
        raise RuntimeError('offline fixture')
    first=investigate_candidates({'candidates':copy.deepcopy(candidates)},source_url='https://brand.example/promotions',fetch=fetch)
    assert len(first['candidates'])==4 and len(calls)==3
    calls.clear()
    investigate_candidates({'candidates':copy.deepcopy(candidates)},source_url='https://brand.example/promotions',fetch=fetch,previous_candidates=first['candidates'])
    assert calls[0].endswith('offer3')


def test_text_backed_offer_can_be_not_detected_without_ocr(database):
    page=store.register('https://brand.example/promotions')
    candidate={'fingerprint':'a','title':'Get free spins','extracted_text':'Get free spins','source_type':'text+image'}
    store.record_promotions(page,'s1','2026-10-19T08:00:00Z',{'text_scan_complete':True,'candidates':[candidate]})
    for i in (2,3):
        store.record_promotions(page,f's{i}',f'2026-10-{19+i}T08:00:00Z',{'text_scan_complete':True,'image_scan_complete':False,'candidates':[]})
    assert store.promotions_for_page(page)[0]['status']=='not_detected'


def test_team_category_override_does_not_confirm_offer():
    result=enrich({'extracted_text':'Get 5% cash back on slots','category_override_json':'["partners"]'})
    assert result['categories']==['partners'] and result['category_source']=='team'
    assert result['verification']['status']=='needs_review'


def test_conflicting_promotion_hours_block_corroboration():
    item=offer()
    item['extracted_text']='Get R100 free bet when you deposit R50. Available 17:00-19:00.'
    item['investigation']['offer_details']['time_windows']=['17:00-19:00']
    item['investigation']['terms_page']['details']['time_windows']=['17:00-21:00']
    assert verify(item)['status']!='automatically_corroborated'


def test_legacy_image_only_to_readable_is_not_reported_as_new_offer_wording(database):
    page=store.register('https://brand.example/promotions')
    image={'fingerprint':'image','title':'banner','extracted_text':'','source_type':'image','details':{}}
    seed_snapshot(database,page,'s1','2026-10-19T08:00:00+00:00',image)
    seed_snapshot(database,page,'s2','2026-10-20T08:00:00+00:00',{**image,'source_type':'text+image','extracted_text':'Get 50 free spins'})
    # Simulate the older history schema, which omitted before values.
    with store.connect() as c:
        row=c.execute('SELECT id,history_json FROM promotions').fetchone()
        history=json.loads(row['history_json'])
        for key in ('previous_text','previous_details','previous_snapshot_id'): history[0].pop(key,None)
        c.execute('UPDATE promotions SET history_json=? WHERE id=?',(json.dumps(history),row['id']))
    event=next(e for e in activity_feed()['events'] if e['kind']=='promotion_change')
    assert event['title']=='Promotion wording became available'
    assert event['previous_snapshot_id']=='s1'


def test_capture_lease_prevents_scheduler_and_dashboard_overlap(database,monkeypatch):
    from monitoring import capture as module
    page=store.register('https://brand.example/promotions')
    stamp=store.now()
    with store.connect() as c:
        c.execute('INSERT INTO captures VALUES (?,?,?,?,?,?,?)',('running',page,'running',stamp,None,None,None))
    monkeypatch.setattr(module,'crawl_page',lambda *a,**k: pytest.fail('A concurrent capture started'))
    with pytest.raises(RuntimeError,match='already running'): module.capture(page)
    assert len(store.captures(page))==1
