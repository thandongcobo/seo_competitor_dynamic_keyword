"""Fifth Gemma request: python -m scripts.run_llm_executive --keyword aviator"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from llm_foundation.executive_synthesis import (build_packet,build_prompt,infer,save_json,
    parse_response,validate_executive)
from llm_foundation.structured_facts import publish_verified_response

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--keyword',required=True)
 p.add_argument('--dry-run',action='store_true')
 p.add_argument('--republish-saved',action='store_true',help='Rebuild the dashboard explanation from the saved local-model response and current evidence without calling the model')
 p.add_argument('--attempts',type=int,default=2)
 args=p.parse_args()
 if args.dry_run and args.republish_saved: p.error('--dry-run and --republish-saved cannot be used together')
 if args.attempts not in (1,2,3): p.error('attempts must be 1-3')
 root=Path('output/results')/args.keyword
 canonical=json.loads((root/'llm_foundation/canonical_evidence.json').read_text(encoding='utf-8'))
 specialists={}
 for task in ('onpage','backlinks','technical','competition'):
  specialists[task]=json.loads((root/'llm_outputs'/f'{task}_validated.json').read_text(encoding='utf-8'))
 packet=build_packet(canonical,specialists)
 skills=Path('llm_foundation/skills.md').read_text(encoding='utf-8')
 instructions=Path('llm_foundation/prompts/executive.md').read_text(encoding='utf-8')
 _,_,tokens=build_prompt(packet,skills,instructions)
 out=root/'llm_outputs'
 save_json(out/'executive_evidence_packet.json',packet)
 print('Executive evidence packet saved; estimated input tokens:',tokens)
 if args.dry_run:
  print('DRY RUN: no LLM request made');return
 if args.republish_saved:
  saved=json.loads((out/'executive_model_raw.json').read_text(encoding='utf-8'))
  parsed=parse_response(saved.get('raw_response'))
  result,repairs=publish_verified_response(parsed,packet)
  save_json(out/'executive_validated.json',result)
  timestamp=datetime.now(timezone.utc).isoformat()
  meta={'model':saved.get('model','saved local model'),'generated_at_utc':timestamp,'keyword':args.keyword,
        'status':'validated','source':'republished saved local-model response; no inference request made',
        'publication_repairs':repairs}
  save_json(out/'executive_run_metadata.json',meta)
  save_json(out/'executive_run_status.json',{'status':'validated','finished_at_utc':timestamp,'model':meta['model']})
  print('Dashboard explanation republished from saved local-model response:',out/'executive_validated.json')
  print('Findings:',len(result['key_findings']),'Decisions:',len(result['proposed_decisions']))
  return
 from openai import OpenAI
 from llm_foundation.inference import load_config
 config=load_config()
 client=OpenAI(base_url=config['base_url'],api_key=config['api_key'])
 save_json(out/'executive_run_status.json',{'status':'running','started_at_utc':datetime.now(timezone.utc).isoformat(),'model':config['model']})
 try:
  result,meta=infer(packet,client,config['model'],skills,instructions,attempts=args.attempts)
 except Exception as exc:
  if getattr(exc,'raw_responses',None):
   save_json(out/'executive_model_raw_invalid.json',{'keyword':args.keyword,'model':config['model'],'attempts':exc.raw_responses})
  save_json(out/'executive_run_status.json',{'status':'failed','finished_at_utc':datetime.now(timezone.utc).isoformat(),'model':config['model'],'error':str(exc)[:500]})
  raise
 raw_response=meta.pop('raw_response')
 save_json(out/'executive_model_raw.json',{'keyword':args.keyword,'model':config['model'],'raw_response':raw_response})
 save_json(out/'executive_validated.json',result)
 meta.update({'model':config['model'],'generated_at_utc':datetime.now(timezone.utc).isoformat(),'keyword':args.keyword})
 save_json(out/'executive_run_metadata.json',meta)
 save_json(out/'executive_run_status.json',{'status':'validated','finished_at_utc':meta['generated_at_utc'],'model':config['model']})
 print('Validated executive response saved:',out/'executive_validated.json')
 print('Findings:',len(result['key_findings']),'Decisions:',len(result['proposed_decisions']),'Attempts:',meta['attempts'])
if __name__=='__main__':main()
