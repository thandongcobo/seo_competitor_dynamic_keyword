"""Stage 3: conservative, compact executive synthesis of validated SEO evidence.
No modifications to the deterministic engine or specialist outputs.
"""
import json
import copy
import re
import math
import os
from pathlib import Path
from jsonschema import Draft202012Validator
from .factual_consistency import check_factual_consistency

TASKS = ('onpage', 'backlinks', 'technical', 'competition')
# No fixed legacy request cap. Optionally set LLM_MAX_INPUT_TOKENS to a verified server limit.
MAX_ESTIMATE = None

class ExecutiveSynthesisError(RuntimeError):
 def __init__(self, message, raw_responses=None):
  super().__init__(message)
  self.raw_responses = raw_responses or []
SCHEMA = {
 'type':'object','additionalProperties':False,
 'required':['schema_version','status','executive_summary','executive_summary_evidence_ids','key_findings','proposed_decisions','limitations'],
 'properties':{
  'schema_version':{'const':'1.0'},'status':{'enum':['usable','insufficient_evidence']},
  'executive_summary':{'type':'string','maxLength':850},
  'executive_summary_evidence_ids':{'type':'array','minItems':1,'items':{'type':'string'}},
   'executive_summary_specialist_finding_ids':{'type':'array','items':{'type':'string'}},
    'key_findings':{'type':'array','maxItems':8,'items':{'type':'object','additionalProperties':False,
    'required':['statement','interpretation','why_it_matters','next_check','evidence_ids','limitation'],
    'properties':{k:{'type':'string','minLength':1} for k in ('statement','interpretation','why_it_matters','next_check','limitation')} | {'evidence_ids':{'type':'array','minItems':1,'items':{'type':'string'}},'specialist_finding_ids':{'type':'array','items':{'type':'string'}}}}},
  'proposed_decisions':{'type':'array','maxItems':3,'items':{'type':'object','additionalProperties':False,
    'required':['title','owner','action','success_check','evidence_ids','limitation'],
    'properties':{k:{'type':'string'} for k in ('title','owner','action','success_check','limitation')} | {'evidence_ids':{'type':'array','minItems':1,'items':{'type':'string'}},'specialist_finding_ids':{'type':'array','items':{'type':'string'}}}}},
  'limitations':{'type':'array','items':{'type':'string'}},
  'potential_ranking_explanations':{'type':'array','items':{'type':'object'}},
  'hollywoodbets_strengths':{'type':'array','items':{'type':'object'}},
  'hollywoodbets_weaknesses_opportunities':{'type':'array','items':{'type':'object'}},
  'recommended_improvements':{'type':'array','maxItems':3,'items':{'type':'object'}},
  'evidence_coverage':{'type':'object'},
  'implementation_plans':{'type':'array','maxItems':20,'items':{'type':'object'}},
  'finding_dispositions':{'type':'array','items':{'type':'object'}}
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
  'evidence_coverage': canonical.get('evidence_coverage') or {}}
 onpage=_get(evidence,'onpage.comparison') or {}
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
  similarity = onpage.get('content_token_jaccard')
  if isinstance(similarity, (int, float)) and not isinstance(similarity, bool) and 0 <= similarity <= 1:
   add('ON_CONTENT_SIMILARITY','Measured content-token Jaccard overlap is lexical similarity only, not semantic relevance, content quality, or ranking causation.',{'content_token_jaccard':similarity})
 if backlinks:
  page=backlinks.get('page') or {}
  domain=backlinks.get('domain') or {}
  add('BL_PAGE','Page-level DataForSEO backlink totals, referring-domain counts, and backlink rank (index score, not Google position); quality and causation unknown.',{s:{k:(page.get(s) or {}).get(k) for k in ('rank','referring_domains','backlinks')} for s in ('ours','benchmark')})
  add('BL_DOMAIN','Domain-level DataForSEO backlink totals, referring-domain counts, and backlink rank (index score, not Google position); these are not page-specific measurements.',{s:{k:(domain.get(s) or {}).get(k) for k in ('rank','referring_domains','backlinks')} for s in ('ours','benchmark')})
 if technical:
  audits=technical.get('mobile_audits') or {}
  add('TECH_LAB','Mobile Lighthouse results are lab data; LCP root cause unverified.',{s:{'scores':(audits.get(s) or {}).get('scores'),'lab_metrics':{k:v for k,v in ((audits.get(s) or {}).get('lab_metrics') or {}).items() if k in ('largest_contentful_paint_ms','total_blocking_time_ms')}} for s in ('ours','benchmark')})
  inv=(technical.get('detailed_analysis') or {}).get('investigations') or []
  add('TECH_INV','Engineering investigations are hypotheses requiring controlled verification.',[{'title':x.get('title'),'priority':x.get('priority')} for x in inv[:4] if isinstance(x,dict)])
 if keywords:
  add('KW_SHARED','Counts of shared generic queries each domain leads on (not average rank positions); results may be different URLs.',{'generic_ours_ahead':keywords.get('generic_ours_ahead'),'generic_benchmark_ahead':keywords.get('generic_benchmark_ahead')})
  # Preserve independently observed per-query ranks, not just aggregate lead counts.
  # Rows are taken from the canonical keyword-intersection evidence only. Reject
  # malformed or inconsistent rows rather than repairing/inventing measurements.
  query_rows = []
  if keywords.get('status') == 'usable':
   for row in keywords.get('top_generic_benchmark_leads') or []:
    if not isinstance(row, dict): continue
    term = row.get('keyword')
    ours, other, gap = (row.get(k) for k in ('our_rank', 'benchmark_rank', 'rank_gap'))
    if not isinstance(term, str) or not term.strip(): continue
    if not all(type(n) is int and n > 0 for n in (ours, other, gap)): continue
    if ours - other != gap: continue
    if row.get('relevance_class') != 'relevant_generic': continue
    verified = {'keyword': term, 'our_rank': ours, 'benchmark_rank': other,
                'rank_gap': gap}
    volume = row.get('search_volume')
    if type(volume) is int and volume >= 0:
     verified['search_volume'] = volume
    query_rows.append(verified)
  if query_rows:
   add('KW_QUERY_GAPS',
       'Saved DataForSEO per-query domain ranking comparisons for selected relevant generic keywords. These may involve different ranking URLs; not the primary exact-page SERP, and no causal ranking conclusion follows.',
       {'queries': query_rows})
 from .information_preservation import specialist_records
 packet['specialist_findings'] = specialist_records(specialist_outputs)
 packet['enriched_evidence'] = copy.deepcopy(canonical.get('enriched_evidence') or {})
 packet['enriched_fact_ids'] = {}
 for task in TASKS:
  packet['enriched_fact_ids'][task] = []
  for item in packet['enriched_evidence'].get(task, []):
   if not isinstance(item, dict) or not item.get('evidence_id'):
    continue
   fact_id = item['evidence_id']
   packet['facts'].append({'id': fact_id,
    'statement': f"Saved {item.get('metric_or_observation')} observation; review limitations before acting.",
    'values': {'observation': item.get('value')},
    'source': item.get('source'), 'collected_at': item.get('collected_at'),
    'keyword': item.get('keyword'), 'page': item.get('page'), 'scope': item.get('scope'),
    'limitations': item.get('limitations'), 'provenance': item.get('provenance')})
   packet['enriched_fact_ids'][task].append(fact_id)
 packet['specialist_fact_links'] = specialist_fact_links(packet)
 return packet

# Specialist identifiers describe LLM interpretations, not independently verified facts.
# This whitelist links only the underlying *approved factual topics* in each source
# path to the executive evidence packet. It does not validate every sentence in a
# specialist finding or promote unsupported measurements to facts.
SPECIALIST_FACT_PATHS = (
 ('evidence.serp.ranking_summary', 'SERP'),
 ('evidence.onpage.comparison.title_keyword_match', 'ON_TITLE'),
 ('evidence.onpage.comparison.internal_link_count', 'ON_LINKS'),
 ('evidence.onpage.comparison.content_token_jaccard', 'ON_CONTENT_SIMILARITY'),
 ('evidence.backlinks.page', 'BL_PAGE'),
 ('evidence.backlinks.domain', 'BL_DOMAIN'),
 ('evidence.technical.mobile_audits', 'TECH_LAB'),
 ('evidence.technical.detailed_analysis.investigations', 'TECH_INV'),
 ('evidence.keywords.intersection.top_generic_benchmark_leads', 'KW_QUERY_GAPS'),
)


def specialist_fact_links(packet):
 """Explicit, conservative provenance links for each specialist finding."""
 approved = {fact['id'] for fact in packet.get('facts', [])}
 links = {}
 for row in packet.get('specialist_findings', []):
  paths = (row.get('finding') or {}).get('evidence_paths') or []
  linked = []
  for path in paths:
   if not isinstance(path, str): continue
   for prefix, fact_id in SPECIALIST_FACT_PATHS:
    if fact_id in approved and (path == prefix or path.startswith(prefix + '.') or path.startswith(prefix + '[')):
     if fact_id not in linked: linked.append(fact_id)
  # Link bounded qualitative records only to findings whose original source
  # path identifies the same evidence family. Legacy findings can therefore
  # use newly preserved source detail without turning their prose into facts.
  task = row.get('task')
  tokens = ' '.join(paths).casefold()
  for item in (packet.get('enriched_evidence') or {}).get(task, []):
   kind = item.get('metric_or_observation', '')
   eligible = ((task == 'onpage' and (
       (kind in ('page_metadata_and_rendering', 'rendered_heading_inventory') and any(t in tokens for t in ('title', 'heading', 'onpage.pages')))
       or (kind == 'outgoing_internal_link_inventory' and 'internal_link_count' in tokens)
       or (kind in ('keyword_relevant_visible_passages', 'observed_content_vocabulary') and any(t in tokens for t in ('content', 'jaccard', 'informational', 'transactional')))
       or (kind == 'structured_data_inventory' and any(t in tokens for t in ('structured', 'schema')))))
       or (task == 'backlinks' and kind.endswith('_backlink_summary') and kind.split('_')[0] in tokens)
       or (task == 'technical' and kind == 'lighthouse_technical_investigations' and 'detailed_analysis' in tokens)
       or (task == 'competition' and kind == 'related_query_domain_rankings' and 'top_generic_benchmark_leads' in tokens)
       or (task == 'competition' and kind.startswith('serp_') and 'ranking_summary' in tokens))
   if eligible and item.get('evidence_id') not in linked:
    linked.append(item['evidence_id'])
  links[row['id']] = linked
 return links


def resolve_evidence_citations(response, packet):
 """Normalize specialist citations into fact citations, retaining lineage.

 A specialist reference with no verified factual mapping is rejected, not
 treated as evidence. This function never modifies the original LLM response.
 """
 normalized = copy.deepcopy(response)
 facts = {fact['id'] for fact in packet.get('facts', [])}
 links = specialist_fact_links(packet)
 errors = []
 def resolve(refs, location):
  resolved, specialists = [], []
  if not isinstance(refs, list):
   return [], [], [f'{location}: evidence_ids must be an array']
  for ref in refs:
   if ref in facts:
    if ref not in resolved: resolved.append(ref)
   elif ref in links:
    if not links[ref]:
     errors.append(f'{location}: specialist finding {ref} has no approved factual mapping; cite a verified FACT ID')
    else:
     specialists.append(ref)
     for fact_id in links[ref]:
      if fact_id not in resolved: resolved.append(fact_id)
   else:
    errors.append(f'{location}: Unknown evidence ID: {ref}')
  return resolved, list(dict.fromkeys(specialists))
 def check_lineage(ids, refs, location):
  if not isinstance(ids, list):
   errors.append(f'{location}: specialist_finding_ids must be an array')
   return []
  for ref in ids:
   if ref not in links:
    errors.append(f'{location}: unknown specialist finding ID: {ref}')
   elif not (set(links[ref]) & set(refs)):
    errors.append(f'{location}: specialist finding {ref} is not linked to any cited approved FACT ID')
  return list(dict.fromkeys(ids))
 refs, lineage = resolve(normalized.get('executive_summary_evidence_ids', []), 'executive_summary')
 normalized['executive_summary_evidence_ids'] = refs
 existing = normalized.get('executive_summary_specialist_finding_ids', [])
 lineage = check_lineage(existing + lineage if isinstance(existing, list) else existing, refs, 'executive_summary')
 if lineage: normalized['executive_summary_specialist_finding_ids'] = lineage
 for section in ('key_findings', 'proposed_decisions', 'implementation_plans'):
  for i, row in enumerate(normalized.get(section, []) if isinstance(normalized.get(section, []), list) else []):
   if not isinstance(row, dict): continue
   refs, lineage = resolve(row.get('evidence_ids', []), f'{section}[{i}]')
   row['evidence_ids'] = refs
   existing = row.get('specialist_finding_ids', [])
   lineage = check_lineage(existing + lineage if isinstance(existing, list) else existing, refs, f'{section}[{i}]')
   if lineage: row['specialist_finding_ids'] = lineage
 return normalized, errors


def estimate_tokens(s): return (len(s)+2)//3

def build_prompt(packet,skills,executive_instructions):
 system=(skills.strip()+'\nUse only evidence IDs in FACTS. No causal ranking claims or financial forecasts.')
 contract=('JSON ONLY: schema_version="1.0", status="usable", executive_summary:string, executive_summary_evidence_ids:[string], '
  'key_findings:[{statement:observed comparison with available values/units, interpretation:keyword-specific hypothesis, why_it_matters:relevance, next_check:validation, evidence_ids:[string],limitation:uncertainty}] max 8, '
  'proposed_decisions:[{title:string,owner:string,action:string,success_check:string,evidence_ids:[string],limitation:string}] max 3, '
  'limitations:[string]. Cite the fact ID for each claim; SERP positions require SERP. IDs must exactly match facts[].id. The optional implementation_plans field is allowed. '
  'For LCP/TBT, lower milliseconds are better; quote numeric values exactly as supplied and do not convert units. Higher DataForSEO backlink rank values are stronger index scores, not higher Google positions. '
  'You may cite an ID from specialist_findings in evidence_ids ONLY when its specialist_fact_links entry is nonempty. Such citations are resolved to approved FACT IDs, and do not validate additional claims or measurements from the specialist prose. Prefer citing the matching FACT IDs directly. Do not cite findings with empty mappings as factual evidence. '
   'For metadata proposals, require verification before changes. Do not prefix individual implementation_steps with numeric step labels. '
  'Optional implementation_plans: [{title,rationale,owner,priority (high|medium|low|investigate), '
  'implementation_steps:[specific executable steps],success_measure,uncertainty,evidence_ids:[FACT IDs], '
  'specialist_finding_ids:[IDs from specialist_findings], simple_explanation:string, technical_explanation:string}]. Preserve the specialist findings in their entirety; '
  'create actionable plans for supported opportunities, and do not invent measured benefits or causal claims. '
  'Treat specialist interpretations as proposals, not as established facts. '
  'MANDATORY finding_dispositions: exactly one entry per specialist_findings ID. Each entry: '
  '{specialist_finding_id, outcome:action|merged|investigate|deferred, plan_indices:[zero-based indices], '
  'simple_explanation:plain English for nontechnical readers, technical_explanation:precise technical rationale, '
  'next_step:specific task, reason:why this outcome, evidence_ids:[approved FACT IDs linked to finding]}. '
  'For actionable findings, cite one or more implementation plans, and each plan must cite the finding ID. '
  'Merge overlapping findings into one plan if useful. For insufficient evidence, choose investigate and specify the next evidence check; '
  'for deferred findings, explain why. Do not invent a ranking cause. '
  'Every implementation plan MUST contain simple_explanation and technical_explanation alongside implementation_steps. '
  'Use only the supplied investigation keyword, domains, and measurements.')
 prompt=executive_instructions.strip()+'\n'+contract+'\nVALIDATED FACTS AND ORIGINAL SPECIALIST PROPOSALS JSON:\n'+json.dumps(packet,ensure_ascii=False,separators=(',',':'))
 tokens=estimate_tokens(system+prompt)
 import os
 limit = int(os.getenv('LLM_MAX_INPUT_TOKENS', '0'))
 if limit > 0 and tokens > limit: raise ValueError(f'Executive prompt estimate {tokens} exceeds configured server limit {limit}')
 return system,prompt,tokens

def parse_response(content):
 if not isinstance(content,str) or not content.strip(): raise ValueError('Empty response')
 s=content.strip()
 if s.startswith('```'):
  s=re.sub(r'^```(?:json)?\s*','',s,flags=re.I)
  s=re.sub(r'\s*```$','',s)
 return json.loads(s)

# Numeric references in implementation instructions are not always measurements.
# Preserve strict checking for observed SEO quantities, while excluding unambiguous
# non-measurement syntax (dates, URLs, technical identifiers and procedural counts).
_NUMERIC_TOKEN = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w,]|\.\d)")
_NON_MEASUREMENT_PATTERNS = (
 re.compile(r"https?://\S+", re.I),
 re.compile(r"\b(?:[A-Za-z]:\\|\./|\.\./)[^\s,;]+"),
 re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b"),
 re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),
 re.compile(r"(?<![\w])#[0-9a-f]{3,8}\b", re.I),
 re.compile(r"\b(?:rgb|rgba|hsl|hsla)\s*\([^)]*\)", re.I),
 re.compile(r"\b(?:v|version\s*)\d+(?:\.\d+){1,4}\b", re.I),
 re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
 re.compile(r"\b(?:step|phase|section|item|task|option)\s*#?\d+\b", re.I),
 re.compile(r"\b(?:run|perform|repeat|compare|review|check|test|audit|create|collect|record|capture|execute|verify)\s+(?:at\s+least\s+)?\d+\s+(?:runs?|tests?|times?|samples?|iterations?|variants?|checks?)\b", re.I),
)
_SEO_QUANTITATIVE_CONTEXT = re.compile(
 r"\b(?:rank(?:ing)?s?|positions?|lcp|tbt|fcp|cls|inp|largest contentful paint|"
 r"total blocking time|contentful paint|backlinks?|referring domains?|"
 r"impressions?|clicks?|ctr|traffic|visits?|conversion rate|"
 r"lighthouse scores?|performance scores?|milliseconds?|ms|seconds?|"
 r"percent(?:age)?|page speed|load time|loading time|"
 r"organic results?|keyword counts?|internal links?|score|javascript payload|"
 r"kilobytes?|megabytes?|kib|mib|kb|mb)\b|%", re.I)


def _numeric_claims(text, *, implementation_step=False):
 """Return (token, offset) for candidate measured numbers in model prose.

 Technical literals and procedural quantities are not claims about observed SEO
 evidence. In implementation steps, only numbers in a quantitative SEO context
 are checked; the separate factual-consistency gate remains in force.
 """
 if not isinstance(text, str):
  return []
 masked = text
 for pattern in _NON_MEASUREMENT_PATTERNS:
  masked = pattern.sub(lambda m: ' ' * (m.end() - m.start()), masked)
 found = []
 for match in _NUMERIC_TOKEN.finditer(masked):
  if implementation_step:
   # Bound the metric context to a clause so an unrelated task number is not
   # mistaken for a measured SEO quantity elsewhere in the instruction.
   left = max(masked.rfind('.', 0, match.start()), masked.rfind(';', 0, match.start()),
              masked.rfind('\n', 0, match.start())) + 1
   right_candidates = [x for x in (masked.find('.', match.end()), masked.find(';', match.end()),
                                  masked.find('\n', match.end())) if x != -1]
   right = min(right_candidates) if right_candidates else len(masked)
   if not _SEO_QUANTITATIVE_CONTEXT.search(masked[left:right]):
    continue
  found.append((match.group(), match.start()))
 return found


def validate_executive(result,packet):
 result, reference_errors = resolve_evidence_citations(result, packet)
 errors = list(reference_errors) + [e.message for e in Draft202012Validator(SCHEMA).iter_errors(result)]
 allowed={f['id'] for f in packet['facts']}
 for field in ('executive_summary_evidence_ids','key_findings','proposed_decisions','implementation_plans'):
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
   for child in value.values(): collect_numbers(child, target)
  elif isinstance(value, list):
   for child in value: collect_numbers(child, target)
 for fact in packet.get('facts', []): collect_numbers(fact.get('values'))
 text_fields = [('executive_summary', result.get('executive_summary', ''), False)]
 for i, finding in enumerate(result.get('key_findings', [])):
  if isinstance(finding, dict):
   text_fields.extend((f'key_findings[{i}].{key}', finding.get(key, ''), False) for key in
                      ('statement','interpretation','why_it_matters','next_check','limitation'))
 for i, row in enumerate(result.get('proposed_decisions', [])):
  if isinstance(row, dict):
   text_fields.extend((f'proposed_decisions[{i}].{key}', row.get(key, ''), False) for key in ('title','action','success_check','limitation'))
 for i, row in enumerate(result.get('implementation_plans', [])):
  if isinstance(row, dict):
   text_fields.extend((f'implementation_plans[{i}].{key}', row.get(key, ''), False) for key in ('title','rationale','success_measure','uncertainty','simple_explanation','technical_explanation'))
   text_fields.extend((f'implementation_plans[{i}].implementation_steps[{j}]', step, True) for j, step in enumerate(row.get('implementation_steps', [])))
 for i, row in enumerate(result.get('finding_dispositions') or []):
  if isinstance(row, dict):
   text_fields.extend((f'finding_dispositions[{i}].{key}', row.get(key, ''), False) for key in ('simple_explanation','technical_explanation','next_step','reason'))
 def supported_for_refs(refs):
  numbers=set()
  for fact in packet.get('facts',[]):
   if fact.get('id') in refs: collect_numbers(fact.get('values'), numbers)
  return numbers
 for location, value, is_step in text_fields:
  if not isinstance(value, str): continue
  for token, _ in _numeric_claims(value, implementation_step=is_step):
   number = float(token.replace(',', ''))
   if not any(math.isclose(number, supported, rel_tol=0.0001, abs_tol=0.51) for supported in supported_numbers):
    errors.append(f'{location}: numeric claim {token} is not present in this run evidence')
 for field, rows in [('executive_summary', [{'evidence_ids':result.get('executive_summary_evidence_ids',[]),'text':result.get('executive_summary','')}]),
                     ('key_findings', result.get('key_findings',[])),('proposed_decisions',result.get('proposed_decisions',[])),('implementation_plans',result.get('implementation_plans',[])),('finding_dispositions',result.get('finding_dispositions',[]))]:
  for i, row in enumerate(rows if isinstance(rows,list) else []):
   if not isinstance(row,dict): continue
   refs=row.get('evidence_ids') or []
   cited=supported_for_refs(refs)
   parts = ([('text', row.get('text', ''), False)] if field == 'executive_summary' else
            [(k, row.get(k, ''), False) for k in
             ('statement','interpretation','why_it_matters','next_check','title','action','success_check','limitation','rationale','success_measure','uncertainty','simple_explanation','technical_explanation','next_step','reason')]
            + [(f'implementation_steps[{j}]', step, True) for j, step in enumerate(row.get('implementation_steps', []))])
   prose = ' '.join(str(value) for _, value, _ in parts)
   for part_name, value, is_step in parts:
    for token, _ in _numeric_claims(value, implementation_step=is_step):
     number=float(token.replace(',', ''))
     if not any(math.isclose(number, supported, rel_tol=0.0001, abs_tol=0.51) for supported in cited):
      errors.append(f'{field}[{i}].{part_name}: numeric claim {token} is not supported by its cited evidence')
   if 'KW_SHARED' in refs and re.search(r'\b(?:generic|shared|related)\s+(?:keyword|query)\s+(?:ranking\s+)?positions?\b', prose, re.I):
    errors.append(f'{field}[{i}]: KW_SHARED values are counts of queries led, not ranking positions')
   if 'ON_LINKS' in refs and re.search(r'\b(?:link\s+density|density\s+of\s+(?:internal\s+)?links|link\s+ratio)\b', prose, re.I):
    errors.append(f'{field}[{i}]: ON_LINKS contains a count, not link density or a ratio')
   if 'KW_SHARED' in refs:
    shared=next((f.get('values') or {} for f in packet.get('facts',[]) if f.get('id')=='KW_SHARED'),{})
    ours_ahead, other_ahead=shared.get('generic_ours_ahead'),shared.get('generic_benchmark_ahead')
    if isinstance(ours_ahead,(int,float)) and isinstance(other_ahead,(int,float)) and ours_ahead!=other_ahead:
     def site_alias(side, base):
      domain=str((packet.get(side) or {}).get('domain') or '')
      label=domain.removeprefix('www.').split('.')[0]
      return '|'.join(re.escape(x) for x in base + ([label] if label else []))
     tracked_lead=bool(re.search(r'\b(?:'+site_alias('tracked',['tracked','ours'])+r')\b.{0,90}\b(?:leads?|ahead|more|stronger)\b.{0,40}\b(?:generic|shared|related|queries|keywords)\b',prose,re.I))
     benchmark_lead=bool(re.search(r'\b(?:'+site_alias('benchmark',['benchmark','competitor'])+r')\b.{0,90}\b(?:leads?|ahead|more|stronger)\b.{0,40}\b(?:generic|shared|related|queries|keywords)\b',prose,re.I))
     if (tracked_lead and ours_ahead<other_ahead) or (benchmark_lead and other_ahead<ours_ahead):
      errors.append(f'{field}[{i}]: generic-query lead claim conflicts with KW_SHARED counts')
 if 'implementation_plans' in result:
  from .information_preservation import validate_plans
  errors.extend(validate_plans(result['implementation_plans'], packet))
 if packet.get('require_action_coverage') or 'finding_dispositions' in result:
  from .action_coverage import validate_action_coverage
  errors.extend(validate_action_coverage(result, packet))
  for i, plan in enumerate(result.get('implementation_plans') or []):
   if isinstance(plan, dict):
    for key in ('simple_explanation', 'technical_explanation'):
     if not isinstance(plan.get(key), str) or not plan[key].strip():
      errors.append(f'implementation_plans[{i}]: missing {key}')
 errors.extend(check_factual_consistency(result, packet))
 return errors

# A repair request may change only a validation-failed field or array entry.
# Paths are derived from validator output, never from a keyword or domain name.
_REPAIR_PATH = re.compile(r"^(?P<root>[A-Za-z_][A-Za-z_0-9]*)(?:\[(?P<index>\d+)\])?(?:\.(?P<field>[A-Za-z_][A-Za-z_0-9]*))?")


def _repair_locations(errors, result):
 """Identify the smallest addressable objects reported by the validator.

 Unknown/unlocated errors fail closed: never ask the model to rewrite the entire
 analysis just to satisfy a validator message.
 """
 allowed = set(SCHEMA['properties'])
 paths = []
 for error in errors:
  match = _REPAIR_PATH.match(error)
  if not match:
   plan = re.match(r'plan (\d+):', error)
   if plan: path = f'implementation_plans[{int(plan.group(1))}]'
   else: return []
  else:
   root, index, field = match.group('root', 'index', 'field')
   # The validator wraps the executive summary as a synthetic single-row
   # section for citation checks; the actual response stores a string.
   if root == 'executive_summary' and index == '0' and field is None:
    index = None
   if root not in allowed or root not in result: return []
   path = root + (f'[{index}]' if index is not None else '') + (f'.{field}' if field else '')
  try: _get_repair_value(result, path)
  except (KeyError, IndexError, TypeError, ValueError): return []
  if path not in paths: paths.append(path)
 # Prefer a parent object over its children when both are implicated.
 return [path for path in paths if not any(path != parent and path.startswith(parent + '.') for parent in paths)]


def _get_repair_value(obj, path):
 match = _REPAIR_PATH.fullmatch(path)
 if not match: raise ValueError('Invalid repair path')
 root, index, field = match.group('root', 'index', 'field')
 if root not in SCHEMA['properties']: raise ValueError('Unknown repair field')
 value = obj[root]
 if index is not None:
  if not isinstance(value, list): raise TypeError('Not an array')
  value = value[int(index)]
 if field is not None:
  if not isinstance(value, dict): raise TypeError('Not an object')
  value = value[field]
 return value


def _apply_repair_patch(original, patch, allowed_paths):
 """Apply an exact-path patch; never permit deletions, inserts, or other edits."""
 if not isinstance(patch, dict) or set(patch) != {'repairs'} or not isinstance(patch['repairs'], list):
  raise ValueError('Repair must be a JSON object with only a repairs array')
 if not patch['repairs']: raise ValueError('Empty repair patch')
 updated = copy.deepcopy(original)
 seen = set()
 for change in patch['repairs']:
  if not isinstance(change, dict) or set(change) != {'path', 'value'}:
   raise ValueError('Each repair must contain only path and value')
  path = change['path']
  if not isinstance(path, str) or path not in allowed_paths or path in seen:
   raise ValueError('Repair contains an unapproved or duplicate path: ' + str(path))
  seen.add(path)
  old = _get_repair_value(updated, path)
  value = change['value']
  if type(old) is not type(value): raise ValueError('Repair changed field type: ' + path)
  # Array entries must retain the original structure and cannot delete
  # previously supported content merely to make validation easier.
  if isinstance(old, dict):
   if set(old) != set(value): raise ValueError('Repair changed object fields: ' + path)
   for key in old:
    if type(old[key]) is not type(value[key]): raise ValueError('Repair changed object field type: ' + path + '.' + key)
  if isinstance(old, list) and len(old) != len(value) and path != 'finding_dispositions':
   raise ValueError('Repair changed array length: ' + path)
  match = _REPAIR_PATH.fullmatch(path)
  root, index, field = match.group('root', 'index', 'field')
  parent = updated
  if index is None and field is None: parent[root] = value
  elif index is not None:
   parent = parent[root]
   if field is None: parent[int(index)] = value
   else: parent[int(index)][field] = value
  else: parent[root][field] = value
 return updated


def _repair_prompt(original, errors, allowed_paths, packet):
 """Give the model factual evidence and an exact patch contract, not a new report."""
 return ('Repair only the specified invalid paths in this existing executive JSON. '
         'Return JSON ONLY: {"repairs":[{"path":"an exact allowed path","value":replacement_value}]}. '
         'Do not rewrite, remove, reorder, or add findings, decisions, or plans. '
         'Keep all existing valid content unchanged. Use only the factual measurements '
         'and evidence identifiers provided. Do not invent SEO metrics or ranking causation.\n'
         'ALLOWED_PATHS: '+json.dumps(allowed_paths)+'\n'
         'VALIDATION_ERRORS: '+json.dumps(errors, ensure_ascii=False)+'\n'
         'APPROVED_FACTS: '+json.dumps(packet.get('facts', []), ensure_ascii=False)+'\n'
         'SPECIALIST_FACT_LINKS: '+json.dumps(packet.get('specialist_fact_links', {}), ensure_ascii=False)+'\n'
         'ORIGINAL_RESPONSE: '+json.dumps(original, ensure_ascii=False))


def infer(packet,client,model,skills,instructions,attempts=2):
 """Validate once, then repair only failing fields; never regenerate valid prose."""
 system,prompt,estimate=build_prompt(packet,skills,instructions)
 last=None
 raw_responses=[]
 original=None
 repaired=None
 repairs=[]
 initial_errors=[]
 for i in range(attempts):
  try:
   max_output=int(os.getenv('LLM_MAX_OUTPUT_TOKENS','0'))
   options={'max_tokens':max_output} if max_output>0 else {}
   is_repair = original is not None
   response=client.chat.completions.create(
    model=model,
    messages=[{'role':'system','content':system},{'role':'user','content':prompt}],
    temperature=0.1,timeout=int(os.getenv('LLM_TIMEOUT_SECONDS','300')),**options)
   choice=response.choices[0]
   if getattr(choice,'finish_reason',None)=='length': raise ValueError('Response truncated by token limit')
   content=choice.message.content
   raw_responses.append({'attempt':i+1,'kind':'targeted_repair' if is_repair else 'initial',
                         'raw_response':content,'finish_reason':getattr(choice,'finish_reason',None)})
   parsed=parse_response(content)
   if is_repair:
    candidate=_apply_repair_patch(original,parsed,repair_paths)
    repairs.append({'attempt':i+1,'paths':[r['path'] for r in parsed['repairs']],
                    'raw_response':content})
   else:
    candidate=parsed
   if packet.get('require_action_coverage'):
    candidate.setdefault('finding_dispositions', [])
    for plan in candidate.get('implementation_plans', []):
     if isinstance(plan, dict):
      plan.setdefault('simple_explanation', '')
      plan.setdefault('technical_explanation', '')
   errs=validate_executive(candidate,packet)
   if errs:
    last='; '.join(errs[:8])
    if i == 0: initial_errors=list(errs)
    if i+1>=attempts: break
    if is_repair:
     # Another repair round may correct a still-invalid field without rewriting
     # already validated content. The next patch starts from this candidate.
     original=candidate
    else:
     original=candidate
    repair_paths=_repair_locations(errs,original)
    if not repair_paths:
     last='Cannot safely localize validation errors: '+last
     break
    prompt=_repair_prompt(original,errs,repair_paths,packet)
    continue
   candidate, reference_errors=resolve_evidence_citations(candidate,packet)
   if reference_errors: raise ValueError('; '.join(reference_errors))
   from llm_foundation.structured_facts import publish_verified_response
   published, publication_repairs=publish_verified_response(candidate,packet)
   # raw_response is ALWAYS the exact first model message.  Normalization and
   # targeted repairs belong in a separate, replayable validated artifact.
   # This keeps the original model output immutable for evidence audits.
   validated_response_json=json.dumps(candidate,ensure_ascii=False)
   return published,{'attempts':i+1,'input_estimated_tokens':estimate,'status':'validated',
                    'validation':'schema, evidence references, metric direction, ranking-causation and metadata-approval checks passed',
                    'raw_response':raw_responses[0]['raw_response'],
                    'validated_response_json':validated_response_json,
                    'original_raw_response':raw_responses[0]['raw_response'],
                    'repair_audit':{'initial_validation_errors':initial_errors,
                                    'patches':repairs,'changed_paths':[path for r in repairs for path in r['paths']]},
                    'publication_repairs':publication_repairs,
                    'note':'Valid fields retained; repairs applied only at explicitly failing paths.'}
  except (ValueError,TypeError,IndexError,AttributeError,KeyError,json.JSONDecodeError) as e:
   last=str(e)
   # Malformed initial JSON has no safe field boundaries; a full retry is
   # possible, but must not be confused with a targeted repair.
   if i+1 < attempts and original is None:
    prompt += '\nThe previous response was invalid JSON: '+last[:500]+'\nReturn a complete valid JSON object.'
    continue
   break
 raise ExecutiveSynthesisError('Executive synthesis failed after '+str(len(raw_responses))+' attempts: '+str(last),raw_responses)

def save_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
