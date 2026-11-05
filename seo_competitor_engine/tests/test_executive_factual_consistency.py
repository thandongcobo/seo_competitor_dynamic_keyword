import copy
from llm_foundation.factual_consistency import check_factual_consistency
from llm_foundation.executive_synthesis import validate_executive

PACKET = {'tracked':{'domain':'hollywoodbets.net','position':2}, 'benchmark':{'domain':'betway.co.za','position':1},
          'facts':[{'id':'SERP','values':{'ours':2,'benchmark':1}}, {'id':'TECH_LAB','values':{'ours':{'scores':{'seo':100,'performance':28},'lab_metrics':{'largest_contentful_paint_ms':24908,'total_blocking_time_ms':2122.5}},'benchmark':{'scores':{'seo':85,'performance':16},'lab_metrics':{'largest_contentful_paint_ms':19507,'total_blocking_time_ms':3272.9}}}}, {'id':'ON_TITLE','values':{}}, {'id':'BL_DOMAIN','values':{'ours':{'rank':70},'benchmark':{'rank':65}}}]}

def output(summary, decisions=None):
    return {'schema_version':'1.0','status':'usable','executive_summary':summary,'executive_summary_evidence_ids':['SERP'],
            'key_findings':[], 'proposed_decisions': decisions or [], 'limitations':[]}

def test_rejects_tbt_reversal():
    assert any('tbt' in x for x in check_factual_consistency(output('The tracked page has higher LCP and TBT than the benchmark.'), PACKET))

def test_accepts_correct_direction():
    assert not check_factual_consistency(output('The tracked page has higher LCP but lower TBT than the benchmark.'), PACKET)

def test_rejects_premature_title_success():
    decision={'title':'Title review','owner':'SEO','action':'Verify the title before deciding on an update', 'success_check':'Title update implemented and verified in SERP.', 'evidence_ids':['ON_TITLE'],'limitation':'No rank guarantee'}
    assert any('unapproved' in x for x in check_factual_consistency(output('Review title.', [decision]), PACKET))

def test_accepts_conditional_title_success():
    decision={'title':'Title review','owner':'SEO','action':'Verify the title before deciding on an update', 'success_check':'If approved, title update implemented and verified in SERP.', 'evidence_ids':['ON_TITLE'],'limitation':'No rank guarantee'}
    # The approved condition should be explicit enough to allow the action.
    assert not check_factual_consistency(output('Review title.', [decision]), PACKET)

def test_integrated_schema_and_evidence_checks():
    assert any('tbt' in x for x in validate_executive(output('The tracked page has higher LCP and TBT than the benchmark.'), PACKET))

def test_missing_metrics_not_assumed():
    p=copy.deepcopy(PACKET)
    next(f for f in p['facts'] if f['id']=='TECH_LAB')['values']['ours']['lab_metrics']={}
    assert not check_factual_consistency(output('The tracked page has higher TBT than the benchmark.'), p)

def test_rejects_real_summary_pattern():
    text = 'The tracked page has a significantly higher LCP and TBT in lab environments compared to the benchmark.'
    assert any('tbt' in x for x in check_factual_consistency(output(text), PACKET))

def test_rejects_unsupported_numeric_claim():
    assert any('numeric claim 999' in x for x in validate_executive(output('The site has 999 backlinks.'), PACKET))

def test_rejects_backlink_rank_direction_reversal():
    summary='Hollywoodbets has a lower backlink rank (70) than Betway (65).'
    assert any('BL_DOMAIN backlink-rank comparison' in x for x in check_factual_consistency(output(summary), PACKET))

def test_rejects_keyword_lead_counts_mislabeled_as_positions():
    packet=copy.deepcopy(PACKET)
    packet['facts'].append({'id':'KW_SHARED','values':{'generic_ours_ahead':24,'generic_benchmark_ahead':31}})
    result=output('Tracked domain leads on 24 generic keyword positions vs 31 for benchmark.')
    result['executive_summary_evidence_ids']=['KW_SHARED']
    assert any('counts of queries led' in x for x in validate_executive(result,packet))

def test_rejects_reversed_generic_query_lead_count():
    packet=copy.deepcopy(PACKET)
    packet['facts'].append({'id':'KW_SHARED','values':{'generic_ours_ahead':24,'generic_benchmark_ahead':31}})
    result=output('The tracked domain leads on generic query counts, 24 vs 31.')
    result['executive_summary_evidence_ids']=['KW_SHARED']
    assert any('generic-query lead claim conflicts' in x for x in validate_executive(result,packet))

def test_rejects_link_count_described_as_density():
    packet=copy.deepcopy(PACKET)
    packet['facts'].append({'id':'ON_LINKS','values':{'ours':9,'benchmark':28}})
    result=output('The benchmark has higher internal link density (28 vs 9).')
    result['executive_summary_evidence_ids']=['ON_LINKS']
    assert any('not link density' in x for x in validate_executive(result,packet))
