"""Versioned, small JSON output contracts for the future local LLM client."""
SPECIALIST_OUTPUT = {
 '$schema':'https://json-schema.org/draft/2020-12/schema', 'type':'object',
 'required':['schema_version','task','status','findings','limitations'],
 'additionalProperties':False,
 'properties':{
  'schema_version':{'const':'1.0'}, 'task':{'enum':['onpage','backlinks','technical','competition']},
  'status':{'enum':['usable','insufficient_evidence']},
  'findings':{'type':'array','maxItems':6,'items':{'type':'object','additionalProperties':False,
    'required':['observation','interpretation','evidence_paths','counterevidence','recommended_action'],
    'properties':{'observation':{'type':'string'},'interpretation':{'type':'string'},
      'evidence_paths':{'type':'array','minItems':1,'items':{'type':'string'}},
      'counterevidence':{'type':'string'},'recommended_action':{'type':'string'}}}},
  'limitations':{'type':'array','items':{'type':'string'}}}}
EXECUTIVE_OUTPUT = {
 '$schema':'https://json-schema.org/draft/2020-12/schema','type':'object',
 'required':['schema_version','executive_summary','key_findings','proposed_decisions','limitations'],
 'additionalProperties':False,
 'properties':{'schema_version':{'const':'1.0'},'executive_summary':{'type':'string'},
 'key_findings':{'type':'array','maxItems':5,'items':{'type':'object',
   'required':['statement','evidence_paths'],'properties':{'statement':{'type':'string'},
   'evidence_paths':{'type':'array','items':{'type':'string'}}},'additionalProperties':False}},
 'proposed_decisions':{'type':'array','maxItems':3,'items':{'type':'object',
   'required':['decision','reason','proposed_owner','validation','evidence_paths'],
   'properties':{'decision':{'type':'string'},'reason':{'type':'string'},
   'proposed_owner':{'type':'string'},'validation':{'type':'string'},
   'evidence_paths':{'type':'array','items':{'type':'string'}}},'additionalProperties':False}},
 'limitations':{'type':'array','items':{'type':'string'}}}}
