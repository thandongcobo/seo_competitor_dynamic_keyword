import pytest
from types import SimpleNamespace
from llm_foundation.executive_synthesis import build_packet,build_prompt,validate_executive,infer

def fixture():
 c={'investigation':{'keyword':'aviator','search_engine':'google'},'tracked_website':{'domain':'a','ranking_url':'https://a/x'},'competitors':[{'domain':'b','ranking_url':'https://b/x'}], 'evidence':{'serp':{'ranking_summary':{'our_position':2,'benchmark_position':1}},'onpage':{'comparison':{'title_keyword_match':{'ours':False,'competitor':True}}}}}
 s={t:{'task':t,'status':'usable','findings':[{'interpretation':'We outrank due to magic.'}]} for t in ('onpage','backlinks','technical','competition')}
 return c,s

def test_gate_does_not_promote_speculation():
 c,s=fixture(); p=build_packet(c,s)
 assert 'magic' not in str(p)
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
 assert result['key_findings'][0]['next_check']
 assert meta['raw_response']==json.dumps(obj)
