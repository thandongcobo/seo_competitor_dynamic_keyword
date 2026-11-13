"""Offline inspector of Lighthouse raw JSON for exact keyword SERP pages."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

AUDIT_IDS = (
    'largest-contentful-paint','largest-contentful-paint-element','lcp-discovery-insight',
    'lcp-breakdown-insight','render-blocking-resources','render-blocking-insight',
    'bootup-time','mainthread-work-breakdown','long-tasks','unused-javascript',
    'unused-css-rules','modern-image-formats','uses-optimized-images',
    'uses-responsive-images','offscreen-images','image-delivery-insight',
    'network-requests','network-rtt','network-server-latency','server-response-time',
    'total-byte-weight','diagnostics','third-party-summary','third-parties-insight',
    'dom-size','font-display','font-display-insight','critical-request-chains',
    'network-dependency-tree-insight','layout-shifts','cls-culprits-insight',
    'total-blocking-time','speed-index','first-contentful-paint',
)
SENSITIVE = ('authorization','cookie','password','token','apikey','api_key','secret')

def slugify(keyword):
    slug = re.sub(r'[^a-z0-9]+','_',keyword.lower()).strip('_')
    if not slug: raise ValueError('Keyword must contain alphanumeric characters')
    return slug

def same_url(a,b):
    if not isinstance(a,str) or not isinstance(b,str): return False
    def norm(v):
        u=urlsplit(v)
        return (u.scheme.lower(),(u.hostname or '').lower(),u.port,u.path.rstrip('/') or '/',u.query)
    return norm(a)==norm(b)

def scrub_url(url):
    """Keep host/path for actionable resource diagnostics; remove query/fragment."""
    if not isinstance(url,str): return None
    p=urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname: return None
    return f'{p.scheme}://{p.hostname}{p.path}'[:250]

def short(value):
    if value is None or isinstance(value,(bool,int,float)): return value
    if isinstance(value,str):
        if any(s in value.lower() for s in SENSITIVE): return '[redacted]'
        return value.replace('\n',' ').replace('\r',' ')[:180]
    return None

def inspect_audit(audit, max_items=4):
    if not isinstance(audit,dict): return {'present':False}
    result={'present':True,'score':short(audit.get('score')),'scoreDisplayMode':short(audit.get('scoreDisplayMode')),
            'numericValue':short(audit.get('numericValue')),'numericUnit':short(audit.get('numericUnit')),
            'displayValue':short(audit.get('displayValue')),'item_count':0,'items':[]}
    details=audit.get('details')
    if isinstance(details,dict):
        raw=details.get('items')
        if isinstance(raw,list):
            result['item_count']=len(raw)
            for item in raw[:max_items]:
                if not isinstance(item,dict):continue
                allowed=('url','source','totalBytes','transferSize','resourceSize','wastedBytes',
                         'wastedMs','duration','startTime','endTime','mainThreadTime','blockingTime',
                         'overallSavingsMs','overallSavingsBytes','entity','group','requestCount',
                         'total','scriptParseCompile','scriptEvaluation','scripting','rendering')
                entry={}
                for key in allowed:
                    if key not in item:continue
                    val=item[key]
                    if key in ('url','source'): val=scrub_url(val)
                    elif isinstance(val,(dict,list)):continue
                    else:val=short(val)
                    if val is not None:entry[key]=val
                if entry:result['items'].append(entry)
    if isinstance(audit.get('warnings'),list):result['warning_count']=len(audit['warnings'])
    return result

def inspect_report(data,expected_url=None,max_items=4):
    if not isinstance(data,dict) or not data.get('lighthouseVersion'):
        raise ValueError('Not a complete Lighthouse JSON report')
    requested=data.get('requestedUrl')
    match=same_url(requested,expected_url) if expected_url else None
    if expected_url and not match:raise ValueError('Lighthouse requestedUrl does not match saved SERP ranking URL')
    audits=data.get('audits') or {}
    if not isinstance(audits,dict):raise ValueError('Invalid Lighthouse audits object')
    return {'lighthouse_version':data.get('lighthouseVersion'),'fetch_time':data.get('fetchTime'),
            'requested_url':scrub_url(requested),'final_url':scrub_url(data.get('finalUrl')),
            'requested_url_matches_serp':match,'audit_count':len(audits),
            'categories':{k:{'score':v.get('score')} for k,v in (data.get('categories') or {}).items() if isinstance(v,dict)},
            'diagnostics':{k:inspect_audit(audits.get(k),max_items) for k in AUDIT_IDS},
            'other_audit_ids':sorted(k for k in audits if k not in AUDIT_IDS),
            'limitations':['Lab observations, not field Core Web Vitals or proven SEO ranking causes.',
                           'Item examples are capped and URL query strings are removed.',
                           'Audit IDs and details differ between Lighthouse versions.']}

def main(argv=None):
    parser=argparse.ArgumentParser(description='Inspect saved raw Lighthouse audits offline')
    parser.add_argument('--keyword',required=True)
    parser.add_argument('--engine',default='google',choices=['google'])
    parser.add_argument('--device',default='mobile',choices=['mobile','desktop'])
    parser.add_argument('--max-items',type=int,default=4)
    parser.add_argument('--results-dir',type=Path,default=None)
    parser.add_argument('--raw-dir',type=Path,default=None)
    args=parser.parse_args(argv)
    if not 1<=args.max_items<=20:parser.error('--max-items must be 1..20')
    root=Path(__file__).resolve().parents[1]
    slug=slugify(args.keyword)
    results=args.results_dir or root/'output'/'results'/slug
    raw=args.raw_dir or root/'data'/'raw'/'lighthouse'
    comparison=results/f'{slug}_comparison.json'
    if not comparison.exists():parser.error(f'Comparison JSON not found: {comparison}')
    try:
        combined=json.loads(comparison.read_text(encoding='utf-8'))
        if str(combined.get('keyword','')).casefold()!=args.keyword.casefold():raise ValueError('Comparison keyword mismatch')
        urls=combined.get('primary_ranking_urls') or {}
        out={'keyword':args.keyword,'engine':args.engine,'device':args.device,
             'source_comparison':comparison.name,'pages':{},'errors':{}}
        for side in ('ours','benchmark'):
            expected=urls.get(side)
            if not expected:raise ValueError(f'Missing primary SERP ranking URL for {side}')
            path=raw/f'{slug}_{args.engine}_{side}_{args.device}.json'
            if not path.exists():
                out['errors'][side]=f'Raw audit missing: {path.name}'
                continue
            try:
                data=json.loads(path.read_text(encoding='utf-8'))
                out['pages'][side]=inspect_report(data,expected,args.max_items)
                out['pages'][side]['source_file']=path.name
            except (OSError,ValueError) as exc:
                out['errors'][side]=str(exc)
        target=results/f'{slug}_lighthouse_diagnostic_inventory.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
        print('Saved:',target)
        for side,page in out['pages'].items():
            present=sum(a['present'] for a in page['diagnostics'].values())
            print(f'{side}: {present}/{len(AUDIT_IDS)} selected audits present; {page["audit_count"]} total audit IDs')
        for side,error in out['errors'].items():print(f'{side}: {error}')
        return 0 if not out['errors'] else 1
    except (ValueError,OSError) as exc:
        parser.error(str(exc))

if __name__=='__main__':raise SystemExit(main())
