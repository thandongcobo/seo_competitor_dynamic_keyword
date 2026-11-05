import json
from types import SimpleNamespace
from llm_foundation.executive_synthesis import build_packet, infer, validate_executive
from llm_foundation.structured_facts import publish_verified_response


def fixture():
    c = {'investigation': {'keyword':'aviator','search_engine':'google'},
         'tracked_website': {'domain':'hollywoodbets.net','ranking_url':'https://hollywoodbets.net/aviator'},
         'competitors': [{'domain':'betway.co.za','ranking_url':'https://betway.co.za/aviator'}],
         'evidence': {
           'serp': {'ranking_summary': {'our_position':2,'benchmark_position':1}},
           'onpage': {'comparison': {'title_keyword_match': {'ours':False,'competitor':True}}},
           'technical': {'mobile_audits': {
             'ours': {'lab_metrics': {'largest_contentful_paint_ms':24908,'total_blocking_time_ms':2122.5}},
             'benchmark': {'lab_metrics': {'largest_contentful_paint_ms':19507,'total_blocking_time_ms':3272.9}}},
             'detailed_analysis': {'investigations': []}}}}
    s = {t: {'task':t,'status':'usable','findings':[]} for t in ('onpage','backlinks','technical','competition')}
    return build_packet(c,s)


def bad_response():
    return {'schema_version':'1.0','status':'usable','executive_summary_evidence_ids':['SERP','TECH_LAB'],
       'executive_summary':'The tracked page has higher LCP and TBT than benchmark.',
       'key_findings':[{'statement':'Tracked page has worse TBT','interpretation':'Possible performance difference.','why_it_matters':'Investigate user experience.','next_check':'Repeat mobile test.','evidence_ids':['TECH_LAB'],'limitation':'Lab'}],
       'proposed_decisions':[{'title':'Title review','owner':'SEO','action':'Consider title update',
         'success_check':'Title contains aviator','evidence_ids':['ON_TITLE'],'limitation':'No rank guarantee'}],
       'limitations':[]}


def test_published_output_corrects_reversal_and_gates_title():
    packet=fixture()
    published, repairs=publish_verified_response(bad_response(),packet)
    assert 'Total Blocking Time' in published['verified_factual_summary']
    assert 'Total Blocking Time' in published['verified_factual_summary']
    assert '24.9s' in published['verified_factual_summary']
    assert '19.5s' in published['verified_factual_summary']
    assert published['executive_summary']==bad_response()['executive_summary']
    assert published['proposed_decisions'][0]['success_check']=='Title contains aviator'
    assert repairs


def test_live_infer_preserves_validated_model_response():
    packet=fixture()
    raw=bad_response()
    raw['executive_summary']='The tracked page has higher LCP but lower TBT than benchmark.'
    raw['key_findings']=[{'statement':'The tracked page has slower LCP but faster TBT than Betway.','interpretation':'The lab results are mixed and may indicate a rendering bottleneck rather than main-thread blocking.','why_it_matters':'The team should target the slow visual load without regressing responsiveness.','next_check':'Repeat comparable mobile Lighthouse runs and inspect field data.','evidence_ids':['TECH_LAB'],'limitation':'Single lab run; not evidence of ranking causation.'}]
    raw['proposed_decisions']=[]
    class Client:
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])))
    result,metadata=infer(packet,Client(),'test','Short skills','Short instructions')
    assert result['key_findings'] == raw['key_findings']
    assert result['key_findings'][0]['evidence_ids'] == ['TECH_LAB']
    assert result['key_findings'][0]['next_check']
    assert metadata['raw_response'] == json.dumps(raw)
    assert metadata['status']=='validated'
    assert metadata['publication_repairs']
    assert all(row['evidence_ids'] for row in result['key_findings'])
