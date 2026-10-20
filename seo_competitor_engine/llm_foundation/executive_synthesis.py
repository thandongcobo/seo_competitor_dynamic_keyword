"""Stage 3: conservative, compact executive synthesis of validated SEO evidence.
No modifications to the deterministic engine or specialist outputs.
"""
import json
import re
import math
import os
from pathlib import Path
from jsonschema import Draft202012Validator
from .factual_consistency import check_factual_consistency

TASKS = ('onpage', 'backlinks', 'technical', 'competition')
MAX_ESTIMATE = 7000

class ExecutiveSynthesisError(RuntimeError):
 def __init__(self, message, raw_responses=None):
  super().__init__(message)
  self.raw_responses = raw_responses or []
SCHEMA = {
 'type':'object','additionalProperties':False,
 'required':['schema_version','status','executive_summary','executive_summary_evidence_ids','key_findings','proposed_decisions','limitations'],
 'properties':{
  'schema_version':{'const':'1.0'},'status':{'enum':['usable','insufficient_evidence']},
  'executive_summary':{'type':'string','maxLength':1800},
  'executive_summary_evidence_ids':{'type':'array','minItems':1,'items':{'type':'string'}},
    'key_findings':{'type':'array','maxItems':8,'items':{'type':'object','additionalProperties':False,
    'required':['statement','interpretation','why_it_matters','next_check','evidence_ids','limitation'],
    'properties':{k:{'type':'string','minLength':1} for k in ('statement','interpretation','why_it_matters','next_check','limitation')} | {'evidence_ids':{'type':'array','minItems':1,'items':{'type':'string'}}}}},
  'proposed_decisions':{'type':'array','maxItems':8,'items':{'type':'object','additionalProperties':False,
    'required':['title','owner','action','success_check','evidence_ids','limitation'],
    'properties':{k:{'type':'string'} for k in ('title','owner','action','success_check','limitation')} | {'evidence_ids':{'type':'array','minItems':1,'items':{'type':'string'}}}}},
  'limitations':{'type':'array','items':{'type':'string'}},
  'potential_ranking_explanations':{'type':'array','items':{'type':'object'}},
  'hollywoodbets_strengths':{'type':'array','items':{'type':'object'}},
  'hollywoodbets_weaknesses_opportunities':{'type':'array','items':{'type':'object'}},
  'recommended_improvements':{'type':'array','maxItems':3,'items':{'type':'object'}},
  'evidence_coverage':{'type':'object'}
 }}

# Curated facts, not the LLM's potentially speculative interpretations.
# Only these verified observations are passed to the fifth request.
FACTS = {
 'onpage':[
  ('title','Title targeting differs; verify the tracked page title before changing it.',('title_keyword_match','title')),
  ('links','Internal-link counts differ; counts do not establish linking quality.',('internal_link_count',)),
  ('similarity','Token overlap is descriptive, not semantic quality.',('content_token_jaccard',))],
 'backlinks':[
  ('page_links','Page-level backlink totals differ; link quality and ranking effects are unknown.',('backlinks.page',)),
  ('domain_links','Domain-wide backlink totals differ; do not attribute domain data to a specific page.',('backlinks.domain',))],
 'technical':[
  ('lab','Mobile Lighthouse scores are single-run lab measurements, not field CWV.',('mobile_audits',)),
  ('lcp','Slow LCP requires investigation; its root cause is unverified.',('lab_metrics',)),
  ('javascript','JavaScript diagnostics identify investigation targets, not proven LCP causes.',('detailed_analysis',))],
 'competition':[
  ('serp','Use only the saved organic SERP to establish ranking positions.',('serp.ranking_summary',)),
  ('related','Related-query ranks are domain-level context and may involve other URLs.',('keywords.intersection',)),
  ('discovery','Discovery candidates are not confirmed SERP competitors.',('competitor_discovery',))]
}

def _get(data,path):
 cur=data
 for key in path.split('.'):
  if not isinstance(cur,dict) or key not in cur: return None
  cur=cur[key]
 return cur

def build_packet(canonical, specialist_outputs):
 """Fail closed on missing tasks; evidence gate only promotes approved factual topics."""
 for task in TASKS:
  row=specialist_outputs.get(task)
  if not isinstance(row,dict) or row.get('task')!=task or row.get('status')!='usable' or not isinstance(row.get('findings'),list):
   raise ValueError('Missing or unusable specialist: '+task)
 investigation=canonical.get('investigation') or {}
 tracked=canonical.get('tracked_website') or {}
 competitors=canonical.get('competitors') or []
 if not tracked.get('ranking_url') or not competitors or not competitors[0].get('ranking_url'):
  raise ValueError('Missing verified ranking identities')
 evidence=canonical.get('evidence') or {}
 ranking=_get(evidence,'serp.ranking_summary') or {}
 if not all(isinstance(ranking.get(k),int) for k in ('our_position','benchmark_position')):
  raise ValueError('Missing ranking positions')
 packet={'schema_version':'1.0','keyword':investigation.get('keyword'),
  'market':investigation.get('market'),'search_engine':investigation.get('search_engine'),
  'tracked':{'domain':tracked.get('domain'),'url':tracked['ranking_url'],'position':ranking['our_position']},
  'benchmark':{'domain':competitors[0].get('domain'),'url':competitors[0]['ranking_url'],'position':ranking['benchmark_position']},
  'facts':[], 'limitations':['Saved SERP snapshot, not live ranking.','No ranking causation or financial return can be inferred.'],
  'evidence_coverage': canonical.get('evidence_coverage') or {},
  'specialist_suggestions': {task:[{'action':str(f.get('recommended_action',''))[:160],
                                   'counterevidence':str(f.get('counterevidence',''))[:100],
                                   'evidence_paths':f.get('evidence_paths',[])[:2]}
                                  for f in specialist_outputs[task].get('findings',[])[:2] if isinstance(f,dict) and f.get('recommended_action')]
                             for task in TASKS}}
 onpage=_get(evidence,'onpage.comparison') or {}
 pages=_get(evidence,'onpage.pages') or {}
 backlinks=_get(evidence,'backlinks') or {}
 technical=_get(evidence,'technical') or {}
 keywords=_get(evidence,'keywords.intersection') or {}
 # Explicit whitelist: never promote free-form LLM interpretations into executive facts.
 def add(id,statement,values):
  packet['facts'].append({'id':id,'statement':statement,'values':values})
 add('SERP','Saved organic SERP positions for the tracked and benchmark URLs; this is a snapshot, not a trend.',
     {'ours':ranking['our_position'],'benchmark':ranking['benchmark_position']})
 if onpage:
  add('ON_TITLE','Tracked and benchmark title keyword presence is an observed difference; verify before editing.',{'title_keyword_match':onpage.get('title_keyword_match')})
  add('ON_LINKS','Internal-link counts are descriptive counts, not density, quality, or causal evidence.',{'internal_link_count':onpage.get('internal_link_count')})
  add('ON_CONTENT','Exact ranking-page metadata and extracted headings; compare relevance and intent without inferring quality from length.',
      {side:{key:(pages.get(side) or {}).get(key) for key in ('title','meta_description','headings','seo_content_word_count','seo_content_status')}
       for side in ('ours','benchmark')})
  if onpage.get('seo_content_comparison') is not None:
   add('ON_COMPARE','Saved cleaned-content comparison; lexical overlap and counts are descriptive only.',
       {'seo_content_comparison':onpage.get('seo_content_comparison'),
        'content_token_jaccard':onpage.get('content_token_jaccard')})
 if backlinks:
  page=backlinks.get('page') or {}
  domain=backlinks.get('domain') or {}
  add('BL_PAGE','Page-level DataForSEO backlink rank (higher value = stronger index score, not Google position); quality and causation unknown.',{s:{k:(page.get(s) or {}).get(k) for k in ('rank','referring_domains')} for s in ('ours','benchmark')})
  add('BL_DOMAIN','Domain-level DataForSEO backlink rank (higher value = stronger index score, not Google position); not page-specific evidence.',{s:{k:(domain.get(s) or {}).get(k) for k in ('rank','referring_domains')} for s in ('ours','benchmark')})
 if technical:
  audits=technical.get('mobile_audits') or {}
  add('TECH_LAB','Mobile Lighthouse results are lab data; LCP root cause unverified.',{s:{'scores':(audits.get(s) or {}).get('scores'),'lab_metrics':{k:v for k,v in ((audits.get(s) or {}).get('lab_metrics') or {}).items() if k in ('largest_contentful_paint_ms','total_blocking_time_ms')}} for s in ('ours','benchmark')})
  inv=(technical.get('detailed_analysis') or {}).get('investigations') or []
  add('TECH_INV','Engineering investigations are hypotheses requiring controlled verification.',
      [{key:(x.get(key)[:1] if key=='affected_resources' and isinstance(x.get(key),list) else x.get(key))
        for key in ('title','priority','measurement','affected_resources') if key in x}
       for x in inv[:4] if isinstance(x,dict)])
 if keywords:
  add('KW_SHARED','Counts of shared generic queries each domain leads on (not average rank positions); results may be different URLs.',{'generic_ours_ahead':keywords.get('generic_ours_ahead'),'generic_benchmark_ahead':keywords.get('generic_benchmark_ahead'),'top_generic_benchmark_leads':(keywords.get('top_generic_benchmark_leads') or [])[:8]})
 return packet

def estimate_tokens(s): return (len(s)+2)//3

def build_prompt(packet,skills,executive_instructions):
 system=(skills.strip()+'\nUse only evidence IDs in FACTS. No causal ranking claims or financial forecasts.')
 contract=('JSON ONLY: schema_version="1.0", status="usable", executive_summary:string, executive_summary_evidence_ids:[string], '
  'key_findings:[{statement:observed comparison with available values/units, interpretation:what the observation may mean, why_it_matters:practical relevance, next_check:specific investigation or validation, evidence_ids:[string],limitation:uncertainty}] up to 8 distinct findings, '
  'proposed_decisions:[{title:string,owner:string,action:specific team action and reason,success_check:observable validation,evidence_ids:[string],limitation:string}] up to 8 distinct decisions, '
  'limitations:[string]. Cite the fact ID for each claim; SERP positions require SERP. IDs must exactly match facts[].id. No other fields. '
  'For LCP/TBT, lower milliseconds are better; quote numeric values exactly as supplied and do not convert units. Higher DataForSEO backlink rank values are stronger index scores, not higher Google positions. '
  'For metadata proposals, require verification before changes. Give useful detail for every supported topic, including strengths and contradictory measurements. Avoid repeated advice and do not fill the quota when evidence is weak. State who should investigate each issue and how the team could tell whether an approved change helped. Keep prose clear for first-time readers. Specialist suggestions are unverified leads, not facts; check them against FACTS before using them. Diagnostic resources are investigation targets, not proven causes of performance metrics. Do not claim title wording is a primary ranking signal. Convert millisecond values to rounded seconds for readability when useful, while retaining correct direction.')
 direction_notes=[]
 for f in structured_direction_notes(packet): direction_notes.append(f)
 prompt=executive_instructions.strip()+'\n'+contract+'\nMEASURED DIRECTIONS:\n'+'\n'.join(direction_notes)+'\nFACTS JSON:\n'+json.dumps(packet,ensure_ascii=False,separators=(',',':'))
 tokens=estimate_tokens(system+prompt)
 budget=int(os.getenv('LLM_EXECUTIVE_INPUT_BUDGET',str(MAX_ESTIMATE)))
 if tokens>budget: raise ValueError(f'Executive prompt estimate {tokens} exceeds {budget}; reduce optional evidence before inference')
 return system,prompt,tokens

def structured_direction_notes(packet):
 """Use source values to spell out easy-to-reverse comparisons for the model."""
 notes=[]
 facts={f.get('id'):f.get('values') for f in packet.get('facts',[])}
 page=facts.get('BL_PAGE') or {}
 ours=(page.get('ours') or {}).get('rank'); other=(page.get('benchmark') or {}).get('rank')
 if isinstance(ours,(int,float)) and isinstance(other,(int,float)):
  notes.append(f'Page-level backlink index: tracked {ours}, benchmark {other}; tracked is '+('lower' if ours<other else 'higher' if ours>other else 'equal')+'. Higher index scores are stronger within this provider metric.')
 lab=facts.get('TECH_LAB') or {}
 for name,key in [('LCP','largest_contentful_paint_ms'),('TBT','total_blocking_time_ms')]:
  a=((lab.get('ours') or {}).get('lab_metrics') or {}).get(key)
  b=((lab.get('benchmark') or {}).get('lab_metrics') or {}).get(key)
  if isinstance(a,(int,float)) and isinstance(b,(int,float)):
   notes.append(f'{name}: tracked {a} ms, benchmark {b} ms; tracked is '+('slower' if a>b else 'faster' if a<b else 'equal')+' in this lab run.')
 return notes

def parse_response(content):
 if not isinstance(content,str) or not content.strip(): raise ValueError('Empty response')
 s=content.strip()
 if s.startswith('```'):
  s=re.sub(r'^```(?:json)?\s*','',s,flags=re.I)
  s=re.sub(r'\s*```$','',s)
 return json.loads(s)

def validate_executive(result,packet):
 errors=[e.message for e in Draft202012Validator(SCHEMA).iter_errors(result)]
 allowed={f['id'] for f in packet['facts']}
 for field in ('executive_summary_evidence_ids','key_findings','proposed_decisions'):
  rows = result.get(field, []) if field != 'executive_summary_evidence_ids' else [{'evidence_ids':result.get(field, [])}]
  for row in rows if isinstance(rows,list) else []:
   if isinstance(row,dict):
    for ref in row.get('evidence_ids',[]):
     if ref not in allowed: errors.append('Unknown evidence ID: '+str(ref))
 # Reject numbers not supported by this run's evidence (allow small display rounding).
 supported_numbers = set()
 for side in ('tracked', 'benchmark'):
  position = (packet.get(side) or {}).get('position')
  if isinstance(position, (int, float)) and not isinstance(position, bool): supported_numbers.add(float(position))
 def collect_numbers(value, target=None):
  target = supported_numbers if target is None else target
  if isinstance(value, bool) or value is None: return
  if isinstance(value, (int, float)): target.add(float(value))
  elif isinstance(value, dict):
   for key, child in value.items():
    if key == 'display' and isinstance(child,str):
     for display_number in re.findall(r'(?<![A-Za-z])\d[\d,]*(?:\.\d+)?',child):
      target.add(float(display_number.replace(',','')))
    else: collect_numbers(child, target)
  elif isinstance(value, list):
   for child in value: collect_numbers(child, target)
 for fact in packet.get('facts', []):
  raw=set(); collect_numbers(fact.get('values'),raw)
  derived={round(n/1000,1) for n in raw if n>1000}
  if len(raw)<=60:
   derived.update(round(abs(a-b),1) for a in raw for b in raw if a!=b)
  supported_numbers.update(raw|derived)
 text_fields = [('executive_summary', result.get('executive_summary', ''))]
 for i, finding in enumerate(result.get('key_findings', [])):
  if isinstance(finding, dict):
   text_fields.extend((f'key_findings[{i}].{key}', finding.get(key, '')) for key in
                      ('statement','interpretation','why_it_matters','next_check','limitation'))
 for i, row in enumerate(result.get('proposed_decisions', [])):
  if isinstance(row, dict):
   text_fields.extend((f'proposed_decisions[{i}].{key}', row.get(key, '')) for key in ('title','action','success_check','limitation'))
 def supported_for_refs(refs):
  numbers=set()
  for fact in packet.get('facts',[]):
   if fact.get('id') in refs:
    raw=set(); collect_numbers(fact.get('values'), raw)
    numbers.update(raw)
    numbers.update(round(n/1000,1) for n in raw if n>1000)
    if len(raw)<=60:
     numbers.update(round(abs(a-b),1) for a in raw for b in raw if a!=b)
  return numbers
 def numeric_claims(text):
  # Asset names and URLs contain digits that are identifiers, not metric claims.
  clean=re.sub(r'https?://\S+|[\w.-]+\.(?:jpg|jpeg|png|webp|js)\b','',text,flags=re.I)
  return re.findall(r'(?<![A-Za-z0-9_])\d[\d,]*(?:\.\d+)?',clean)
 for location, value in text_fields:
  if not isinstance(value, str): continue
  for token in numeric_claims(value):
   number = float(token.replace(',', ''))
   if not any(math.isclose(number, supported, rel_tol=0.0001, abs_tol=0.51) for supported in supported_numbers):
    errors.append(f'{location}: numeric claim {token} is not present in this run evidence')
 for field, rows in [('executive_summary', [{'evidence_ids':result.get('executive_summary_evidence_ids',[]),'text':result.get('executive_summary','')}]),
                     ('key_findings', result.get('key_findings',[])),('proposed_decisions',result.get('proposed_decisions',[]))]:
  for i, row in enumerate(rows if isinstance(rows,list) else []):
   if not isinstance(row,dict): continue
   refs=row.get('evidence_ids') or []
   cited=supported_for_refs(refs)
   prose=row.get('text') if field=='executive_summary' else ' '.join(str(row.get(k,'')) for k in ('statement','interpretation','why_it_matters','next_check','title','action','success_check','limitation'))
   for token in numeric_claims(prose or ''):
    number=float(token.replace(',',''))
    if not any(math.isclose(number, supported, rel_tol=0.0001, abs_tol=0.51) for supported in cited):
     errors.append(f'{field}[{i}]: numeric claim {token} is not supported by its cited evidence')
   if 'KW_SHARED' in refs and re.search(r'\b(?:generic|shared|related)\s+(?:keyword|query)\s+(?:ranking\s+)?positions?\b', prose, re.I):
    errors.append(f'{field}[{i}]: KW_SHARED values are counts of queries led, not ranking positions')
   if 'ON_LINKS' in refs and re.search(r'\b(?:link\s+density|density\s+of\s+(?:internal\s+)?links|link\s+ratio)\b', prose, re.I):
    errors.append(f'{field}[{i}]: ON_LINKS contains a count, not link density or a ratio')
   if 'BL_PAGE' in refs:
    page_values=next((f.get('values') or {} for f in packet.get('facts',[]) if f.get('id')=='BL_PAGE'),{})
    ours_rank=(page_values.get('ours') or {}).get('rank'); benchmark_rank=(page_values.get('benchmark') or {}).get('rank')
    if isinstance(ours_rank,(int,float)) and isinstance(benchmark_rank,(int,float)) and ours_rank<benchmark_rank:
     if re.search(r'\b(?:tracked|ours|hollywoodbets)\b.{0,75}\b(?:higher|stronger|greater)\b.{0,35}\b(?:page.level\s+)?backlink\s+rank\b',prose,re.I):
      errors.append(f'{field}[{i}]: tracked page backlink rank is lower than benchmark')
     if re.search(r'\b(?:tracked|ours|hollywoodbets)\b.{0,100}\b(?:higher|stronger|greater)\b.{0,45}\b(?:page.level|index\s+score|backlink)\b',prose,re.I):
      errors.append(f'{field}[{i}]: tracked page index score cannot be described as stronger')
   if field=='key_findings' and 'TECH_INV' in refs:
    interpretation=' '.join(str(row.get(k,'')) for k in ('interpretation','why_it_matters'))
    if re.search(r'\b(?:primary contributor|directly contributes|proven cause|root cause)\b',interpretation,re.I):
     errors.append(f'{field}[{i}]: technical diagnostic does not prove the page bottleneck')
   if field=='key_findings' and 'TECH_LAB' in refs:
    lab_values=next((f.get('values') or {} for f in packet.get('facts',[]) if f.get('id')=='TECH_LAB'),{})
    statement=str(row.get('statement',''))
    for label,key in [('LCP','largest_contentful_paint_ms'),('TBT','total_blocking_time_ms')]:
     a=((lab_values.get('ours') or {}).get('lab_metrics') or {}).get(key)
     b=((lab_values.get('benchmark') or {}).get('lab_metrics') or {}).get(key)
     if isinstance(a,(int,float)) and isinstance(b,(int,float)) and a<b:
      if re.search(r'\btracked\b.{0,65}\b(?:worse|slower|higher)\s+'+label+r'\b',statement,re.I):
       errors.append(f'{field}[{i}]: tracked {label} is lower than benchmark in this lab run')
   if field=='key_findings' and 'ON_TITLE' in refs:
    interpretation=' '.join(str(row.get(k,'')) for k in ('interpretation','why_it_matters'))
    if re.search(r'\b(?:primary|major)\s+(?:ranking\s+)?signal\b',interpretation,re.I):
     errors.append(f'{field}[{i}]: keyword presence does not establish ranking weight')
   if 'KW_SHARED' in refs:
    shared=next((f.get('values') or {} for f in packet.get('facts',[]) if f.get('id')=='KW_SHARED'),{})
    ours_ahead, other_ahead=shared.get('generic_ours_ahead'),shared.get('generic_benchmark_ahead')
    if isinstance(ours_ahead,(int,float)) and isinstance(other_ahead,(int,float)) and ours_ahead!=other_ahead:
     tracked_lead=bool(re.search(r'\b(?:tracked|ours|hollywoodbets)\b.{0,90}\b(?:leads?|ahead|more|stronger)\b.{0,40}\b(?:generic|shared|related|queries|keywords)\b',prose,re.I))
     benchmark_lead=bool(re.search(r'\b(?:benchmark|betway|competitor)\b.{0,90}\b(?:leads?|ahead|more|stronger)\b.{0,40}\b(?:generic|shared|related|queries|keywords)\b',prose,re.I))
     if (tracked_lead and ours_ahead<other_ahead) or (benchmark_lead and other_ahead<ours_ahead):
      errors.append(f'{field}[{i}]: generic-query lead claim conflicts with KW_SHARED counts')
 errors.extend(check_factual_consistency(result, packet))
 return errors

def infer(packet,client,model,skills,instructions,attempts=2):
 system,prompt,estimate=build_prompt(packet,skills,instructions)
 last=None
 raw_responses=[]
 for i in range(attempts):
  try:
   response=client.chat.completions.create(model=model,messages=[{'role':'system','content':system},{'role':'user','content':prompt}],temperature=0.1,timeout=240,max_tokens=int(os.getenv('LLM_EXECUTIVE_OUTPUT_BUDGET','2400')))
   choice=response.choices[0]
   if getattr(choice,'finish_reason',None)=='length': raise ValueError('Response truncated by token limit')
   content=choice.message.content
   raw_responses.append({'attempt':i+1,'raw_response':content,'finish_reason':getattr(choice,'finish_reason',None)})
   parsed=parse_response(content)
   # Validate each claim and retain the supported findings. An unsupported
   # sentence must never force otherwise valid evidence off the dashboard.
   from llm_foundation.structured_facts import publish_verified_response
   parsed, publication_repairs = publish_verified_response(parsed,packet)
   # Keep the local model's evidence-grounded analysis intact after validation.
   # Deterministic facts remain in the evidence packet and are not silently substituted for prose.
   return parsed,{'attempts':i+1,'input_estimated_tokens':estimate,'status':'validated',
                  'validation':'schema, evidence references, metric direction, ranking-causation and metadata-approval checks passed',
                  'raw_response':content,
                  'publication_repairs':publication_repairs,
                  'note':'The dashboard explanation is enriched from cited, validated measurements; the exact local-model response is also saved in executive_model_raw.json.'}
  except (ValueError,TypeError,IndexError,AttributeError,json.JSONDecodeError) as e:
   last=str(e)
   # Small, bounded correction instruction; avoid repeating a factual error verbatim.
   if i + 1 < attempts:
    page_fact=next((f.get('values') or {} for f in packet.get('facts',[]) if f.get('id')=='BL_PAGE'),{})
    ours_rank=(page_fact.get('ours') or {}).get('rank')
    other_rank=(page_fact.get('benchmark') or {}).get('rank')
    prompt += ('\nCorrection: recheck every comparison direction against FACTS. Cite the source ID for every number; '
               'positions require SERP. KW_SHARED counts queries led; ON_LINKS counts links, not density. '
               f'Page-level backlink rank is tracked {ours_rank} versus benchmark {other_rank}; larger is stronger. '
               'LCP and TBT are separate lab metrics; do not describe both as worse if only one is worse.')
 raise ExecutiveSynthesisError('Executive synthesis failed after '+str(attempts)+' attempts: '+str(last),raw_responses)

def save_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
