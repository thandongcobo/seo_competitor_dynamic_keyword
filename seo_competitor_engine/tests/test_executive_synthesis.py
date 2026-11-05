import pytest
from types import SimpleNamespace
from llm_foundation.executive_synthesis import build_packet,build_prompt,validate_executive,infer

def fixture():
 c={'investigation':{'keyword':'aviator','search_engine':'google'},'tracked_website':{'domain':'a','ranking_url':'https://a/x'},'competitors':[{'domain':'b','ranking_url':'https://b/x'}], 'evidence':{'serp':{'ranking_summary':{'our_position':2,'benchmark_position':1}},'onpage':{'comparison':{'title_keyword_match':{'ours':False,'competitor':True}}}}}
 s={t:{'task':t,'status':'usable','findings':[{'interpretation':'We outrank due to magic.'}]} for t in ('onpage','backlinks','technical','competition')}
 return c,s

def test_gate_does_not_promote_speculation():
 c,s=fixture(); p=build_packet(c,s)
 assert 'magic' not in str(p['facts'])
 assert 'magic' in str(p['specialist_findings'])
 assert next(f for f in p['facts'] if f['id']=='ON_TITLE')

def test_missing_specialist_rejected():
 c,s=fixture();s.pop('technical')
 with pytest.raises(ValueError):build_packet(c,s)

def test_reference_rejection():
 c,s=fixture();p=build_packet(c,s)
 r={'schema_version':'1.0','status':'usable','executive_summary':'Summary','executive_summary_evidence_ids':['SERP'],'key_findings':[{'statement':'X','interpretation':'Y','why_it_matters':'Z','next_check':'Check','evidence_ids':['FAKE'],'limitation':'Unknown'}],'proposed_decisions':[],'limitations':[]}
 assert validate_executive(r,p)

def test_mock_inference():
 import json
 c,s=fixture();p=build_packet(c,s)
 obj={'schema_version':'1.0','status':'usable','executive_summary':'Review title','executive_summary_evidence_ids':['ON_TITLE'],'key_findings':[{'statement':'Title differs','interpretation':'The tracked page may be less explicit about the query.','why_it_matters':'Searchers should understand the page topic.','next_check':'Verify the rendered title and search appearance.','evidence_ids':['ON_TITLE'],'limitation':'Not causal'}],'proposed_decisions':[],'limitations':[]}
 class Client:
  chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs:SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(obj)),finish_reason='stop')])))
 result,meta=infer(p,Client(),'test','Short skills','Short instructions')
 assert result['key_findings'][0]['evidence_ids']==['ON_TITLE'] and meta['status']=='validated'
 assert result['executive_summary']=='Review title'
 assert 'saved Google results' in result['verified_factual_summary']
 assert result['key_findings'][0]['next_check']
 assert meta['raw_response']==json.dumps(obj)


def test_real_aviator_specialist_fact_registry_is_conservative():
 from pathlib import Path
 import json
 root = Path(__file__).resolve().parents[1] / 'output/results/aviator'
 canonical = json.loads((root/'llm_foundation/canonical_evidence.json').read_text())
 specialists = {t: json.loads((root/'llm_outputs'/f'{t}_validated.json').read_text())
                for t in ('onpage','backlinks','technical','competition')}
 packet = build_packet(canonical, specialists)
 links = packet['specialist_fact_links']
 assert links['ONPAGE_01'] == ['ON_TITLE']
 assert links['ONPAGE_02'] == ['ON_LINKS']
 assert links['TECHNICAL_02'] == ['TECH_LAB']
 assert links['TECHNICAL_03'] == ['TECH_INV']
 assert links['COMPETITION_01'] == ['SERP', 'KW_QUERY_GAPS']
 assert links['ONPAGE_03'] == ['ON_CONTENT_SIMILARITY']  # Approved lexical measurement only.
 assert links['COMPETITION_02'] == ['KW_QUERY_GAPS']  # Verified per-query domain ranks are approved.


def test_specialist_citation_resolves_to_verified_fact_without_losing_lineage():
 import json
 from pathlib import Path
 from llm_foundation.executive_synthesis import resolve_evidence_citations
 root = Path(__file__).resolve().parents[1] / 'output/results/aviator'
 canonical = json.loads((root/'llm_foundation/canonical_evidence.json').read_text())
 specialists = {t: json.loads((root/'llm_outputs'/f'{t}_validated.json').read_text())
                for t in ('onpage','backlinks','technical','competition')}
 packet = build_packet(canonical, specialists)
 raw = {'schema_version':'1.0','status':'usable','executive_summary':'Review title relevance.',
        'executive_summary_evidence_ids':['ONPAGE_01'],
        'key_findings':[{'statement':'The tracked page title does not include the keyword.',
                         'interpretation':'Potential topic clarity issue.', 'why_it_matters':'User relevance.',
                         'next_check':'Verify the title.', 'evidence_ids':['ONPAGE_01'],
                         'limitation':'No causal ranking proof.'}],
        'proposed_decisions':[],'limitations':[]}
 assert validate_executive(raw,packet) == []
 fixed,errors=resolve_evidence_citations(raw,packet)
 assert not errors
 assert fixed['executive_summary_evidence_ids']==['ON_TITLE']
 assert fixed['executive_summary_specialist_finding_ids']==['ONPAGE_01']
 assert fixed['key_findings'][0]['evidence_ids']==['ON_TITLE']
 assert fixed['key_findings'][0]['specialist_finding_ids']==['ONPAGE_01']
 assert raw['key_findings'][0]['evidence_ids']==['ONPAGE_01']  # Immutable raw response.


def test_unsupported_specialist_citation_still_fails():
 import json
 from pathlib import Path
 root = Path(__file__).resolve().parents[1] / 'output/results/aviator'
 canonical = json.loads((root/'llm_foundation/canonical_evidence.json').read_text())
 specialists = {t: json.loads((root/'llm_outputs'/f'{t}_validated.json').read_text())
                for t in ('onpage','backlinks','technical','competition')}
 packet = build_packet(canonical, specialists)
 raw = {'schema_version':'1.0','status':'usable','executive_summary':'Overlap difference.',
        'executive_summary_evidence_ids':['COMPETITION_03'], 'key_findings':[],
        'proposed_decisions':[], 'limitations':[]}
 assert any('no approved factual mapping' in error for error in validate_executive(raw,packet))
 raw['executive_summary_evidence_ids']=['NOT_REAL_01']
 assert any('Unknown evidence ID' in error for error in validate_executive(raw,packet))


def test_specialist_citation_does_not_authorize_unverified_number():
 import json
 from pathlib import Path
 root = Path(__file__).resolve().parents[1] / 'output/results/aviator'
 canonical = json.loads((root/'llm_foundation/canonical_evidence.json').read_text())
 specialists = {t: json.loads((root/'llm_outputs'/f'{t}_validated.json').read_text())
                for t in ('onpage','backlinks','technical','competition')}
 packet = build_packet(canonical, specialists)
 raw = {'schema_version':'1.0','status':'usable','executive_summary':'A JavaScript issue of 1108 KiB was detected.',
        'executive_summary_evidence_ids':['TECHNICAL_03'], 'key_findings':[],
        'proposed_decisions':[], 'limitations':[]}
 assert any('numeric claim 1108' in error for error in validate_executive(raw,packet))


def test_infer_accepts_valid_specialist_alias_and_publishes_fact_id():
 import json
 from pathlib import Path
 root = Path(__file__).resolve().parents[1] / 'output/results/aviator'
 canonical = json.loads((root/'llm_foundation/canonical_evidence.json').read_text())
 specialists = {t: json.loads((root/'llm_outputs'/f'{t}_validated.json').read_text())
                for t in ('onpage','backlinks','technical','competition')}
 packet = build_packet(canonical, specialists)
 obj = {'schema_version':'1.0','status':'usable','executive_summary':'Review the captured title.',
        'executive_summary_evidence_ids':['ONPAGE_01'], 'key_findings':[],
        'proposed_decisions':[], 'limitations':[]}
 class Client:
  chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
      choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(obj)),finish_reason='stop')])))
 published, meta=infer(packet,Client(),'fixture','skills','instructions',attempts=1)
 assert meta['status']=='validated'
 assert published['executive_summary_evidence_ids']==['ON_TITLE']
 assert published['executive_summary_specialist_finding_ids']==['ONPAGE_01']
 assert json.loads(meta['raw_response'])==obj
