from llm_foundation.structured_facts import structured_facts, publish_verified_response
from llm_foundation.executive_synthesis import validate_executive


def packet():
    return {'keyword':'aviator', 'tracked':{'domain':'ours.test','position':2},
            'benchmark':{'domain':'other.test','position':1},
            'facts':[{'id':'TECH_LAB','values':{
                'ours':{'lab_metrics':{'largest_contentful_paint_ms':24908,'total_blocking_time_ms':2122}},
                'benchmark':{'lab_metrics':{'largest_contentful_paint_ms':19507,'total_blocking_time_ms':3273}}}},
                {'id':'ON_TITLE','values':{'title_keyword_match':{'ours':False,'competitor':True}}}]}


def response():
    return {'schema_version':'1.0','status':'usable','executive_summary':'Tracked LCP is slower but TBT is faster in this lab run.',
            'executive_summary_evidence_ids':['TECH_LAB'],
            'key_findings':[{'statement':'Tracked TBT is faster','interpretation':'This lab measure differs from LCP.',
                             'why_it_matters':'Review both metrics.','next_check':'Repeat the mobile test.',
                             'evidence_ids':['TECH_LAB'],'limitation':'Lab result, not field data.'}],
            'proposed_decisions':[{'title':'Title','owner':'SEO','action':'Evaluate title',
                                   'success_check':'Title contains aviator','evidence_ids':['ON_TITLE'],
                                   'limitation':'Not guaranteed'}], 'limitations':[]}


def test_directions_and_presentation():
    facts = {f['id']:f for f in structured_facts(packet())}
    assert facts['TECH_LCP']['better'] == 'benchmark'
    assert facts['TECH_TBT']['better'] == 'ours'
    output, changes = publish_verified_response(response(), packet())
    assert output['executive_summary']==response()['executive_summary']
    assert 'key_findings' in output
    assert all(all(f.get(key) for key in ('statement','interpretation','why_it_matters','next_check','limitation'))
               for f in output['key_findings'])
    assert any('not field data' in f['limitation'] for f in output['key_findings'] if 'TECH_LAB' in f['evidence_ids'])
    assert 'Verify' in output['proposed_decisions'][0]['success_check']
    assert len(changes) == 1


def test_missing_metric_not_invented():
    p=packet(); p['facts'][0]['values']['benchmark']['lab_metrics'].pop('total_blocking_time_ms')
    assert 'TECH_TBT' not in {f['id'] for f in structured_facts(p)}


def test_does_not_mutate_model_response():
    raw=response(); publish_verified_response(raw,packet())
    assert raw['executive_summary']=='Tracked LCP is slower but TBT is faster in this lab run.'
