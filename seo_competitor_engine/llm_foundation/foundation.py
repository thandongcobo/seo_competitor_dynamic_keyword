"""Convert the existing SEO comparison (v0.5) into evidence-gated specialist packets.
No network calls, LLM inference or changes to the source JSON.
"""
from __future__ import annotations
import copy
import json
from .evidence_coverage import build_coverage_manifest
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SPECIALISTS = {
    'onpage': ('serp', 'onpage', 'intent'),
    'backlinks': ('serp', 'backlinks'),
    'technical': ('serp', 'technical'),
    'competition': ('serp', 'keywords', 'competitor_discovery'),
}

def obj(v):
    return v if isinstance(v, dict) else {}

def rows(v):
    return v if isinstance(v, list) else []

def clean_url(url):
    if not isinstance(url, str):
        return None
    try:
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname:
            return None
        host = p.hostname.lower()
        return urlunsplit((p.scheme.lower(), host, p.path.rstrip('/') or '/', '', ''))
    except ValueError:
        return None

def scrub(value):
    """Drop secrets and raw text; strip URL query strings in retained evidence."""
    banned = {'location_coordinate', 'diagnostic_directory', 'text_sample', 'seo_content_text',
              'api_key', 'authorization', 'password', 'cookie', 'token', 'raw_html', 'screenshot'}
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k.lower() not in banned}
    if isinstance(value, list):
        return [scrub(x) for x in value]
    if isinstance(value, str) and value.startswith(('http://', 'https://')):
        return clean_url(value)
    return value

def canonicalize(source):
    if not isinstance(source, dict):
        raise ValueError('Comparison JSON must be an object')
    keyword = source.get('keyword')
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError('Missing keyword')
    ranking = obj(obj(source.get('ranking_summary')).get('google'))
    urls = obj(source.get('primary_ranking_urls'))
    ours_url, competitor_url = clean_url(urls.get('ours')), clean_url(urls.get('benchmark'))
    if not ours_url or not competitor_url:
        raise ValueError('Missing valid primary Google ranking URLs')
    pages = obj(source.get('page_level_evidence'))
    quality = obj(source.get('evidence_quality'))
    page_valid = {}
    for side, expected in [('ours', ours_url), ('benchmark', competitor_url)]:
        page = obj(pages.get(side))
        page_valid[side] = (quality.get('page_'+side) == 'usable'
            and page.get('url_alignment') == 'matched'
            and page.get('extraction_status') == 'complete'
            and clean_url(page.get('ranking_url')) == expected
            and clean_url(page.get('requested_url')) == expected
            and clean_url(page.get('final_url')) == expected)
    onpage = obj(source.get('onpage_comparison'))
    comparable = obj(onpage.get('seo_content_comparison')).get('comparable') is True and all(page_valid.values())
    safe_pages = {}
    for side in ('ours', 'benchmark'):
        page = obj(pages.get(side))
        safe_pages[side] = ({k: page.get(k) for k in ('title','meta_description','headings','h1_count',
            'internal_link_count','external_link_count','structured_data_count',
            'seo_content_word_count','seo_content_status','seo_content_method')} |
            {'seo_content_excerpt': (page.get('seo_content_text') or '')[:5000]}
            if page_valid[side] else {'status': 'withheld', 'reason': quality.get('page_'+side, 'unverified')})
    comparison = {k: v for k,v in onpage.items() if k not in ('word_count','main_word_count',
        'legacy_main_word_count_diagnostic')}
    if not comparable:
        for k in ('seo_content_comparison','content_token_jaccard','top_shared_terms',
                  'transactional_term_hits','informational_term_hits'):
            comparison.pop(k, None)
    lighthouse = obj(pages.get('lighthouse'))
    audits = {}
    for side, expected in (('ours', ours_url), ('benchmark', competitor_url)):
        audit = obj(obj(lighthouse.get(side)).get('mobile'))
        valid = (quality.get('lighthouse_'+side+'_mobile') == 'usable'
                 and audit.get('status') == 'usable' and audit.get('target_verified') is True
                 and audit.get('final_url_verified') is True
                 and clean_url(audit.get('ranking_url')) == expected)
        audits[side] = ({'scores': audit.get('scores'), 'lab_metrics': audit.get('lab_metrics'),
                         'technical_diagnostics': audit.get('technical_diagnostics')}
                        if valid else {'status': 'withheld'})
    technical = obj(obj(source.get('technical_comparison')).get('mobile'))
    detailed = obj(technical.get('detailed_analysis'))
    if not (all(a.get('status') != 'withheld' for a in audits.values()) and detailed.get('status') == 'usable'):
        detailed = {'status': 'withheld'}
    backlinks = {}
    for scope in ('page', 'domain'):
        if scope == 'page':
            backlink_data = {side: obj(pages.get('backlinks_'+side if side == 'ours' else 'backlinks_benchmark')) for side in ('ours','benchmark')}
            for side, expected in [('ours',ours_url),('benchmark',competitor_url)]:
                d = backlink_data[side]
                if not (quality.get('backlinks_'+side+'_page') == 'usable' and d.get('scope') == 'page'
                        and d.get('target_verified') is True and clean_url(d.get('target')) == expected):
                    backlink_data[side] = {'status':'withheld'}
        else:
            domain = obj(source.get('domain_level_evidence'))
            backlink_data = {side: obj(domain.get('backlinks_'+side if side == 'ours' else 'backlinks_benchmark')) for side in ('ours','benchmark')}
            for side in ('ours','benchmark'):
                d = backlink_data[side]
                if d.get('scope') != 'domain' or d.get('target_verified') is not True:
                    backlink_data[side] = {'status':'withheld'}
        backlinks[scope] = backlink_data
    advanced = obj(source.get('advanced_evidence'))
    intersection = obj(advanced.get('keyword_intersection'))
    candidates = rows(source.get('potential_competitors'))
    canonical = scrub({
        'schema_version': '1.0',
        'investigation': {'keyword':keyword,'search_engine':'google','market':source.get('labs_location'),
                          'source_schema_version':source.get('schema_version'), 'source_type':'saved_serp_snapshot'},
        'tracked_website': {'domain':source.get('our_domain'),'ranking_url':ours_url,'position':ranking.get('our_position')},
        'competitors': [{'domain':source.get('benchmark_competitor_domain'), 'ranking_url':competitor_url,
                         'position':ranking.get('benchmark_position'), 'role':'confirmed_benchmark'}],
        'evidence_quality': quality,
        'evidence': {
            'serp': {'ranking_summary': ranking,'primary_ranking_urls':{'ours':ours_url,'benchmark':competitor_url}},
            'onpage': {'pages':safe_pages,'comparison':comparison,'comparable':comparable},
            'backlinks':backlinks,
            'technical': {'mobile_audits':audits,'detailed_analysis':detailed},
            'keywords': {'intersection': {'status':intersection.get('status'),
                'returned':intersection.get('returned'), 'generic_ours_ahead':intersection.get('generic_ours_ahead'),
                'generic_benchmark_ahead':intersection.get('generic_benchmark_ahead'),
                'top_generic_benchmark_leads':rows(intersection.get('top_generic_benchmark_leads'))[:10],
                'warnings':intersection.get('warnings')},
                'intent':source.get('intent_alignment')},
            'competitor_discovery': {'candidates': [
                {'domain':r.get('domain'),'serp_present':r.get('serp_present'),
                 'nearest_serp_rank':r.get('nearest_serp_rank'), 'benchmark':r.get('benchmark')}
                for r in candidates[:30] if isinstance(r,dict)],
                'note':'Discovery candidates are not verified SERP rankings.'},
        },
        'deterministic_findings': rows(source.get('findings')),
        'deterministic_recommendations': rows(source.get('recommendations')),
        'limitations': obj(source.get('analysis_policy')),
    })
    canonical['evidence_coverage'] = build_coverage_manifest(source)
    return canonical

def make_packets(canonical):
    evidence = obj(canonical.get('evidence'))
    common = {k:copy.deepcopy(canonical[k]) for k in ('schema_version','investigation',
        'tracked_website','competitors','evidence_quality')}
    packets = {}
    for specialist, sections in SPECIALISTS.items():
        packet = copy.deepcopy(common)
        packet['task'] = specialist
        packet['evidence'] = {section:copy.deepcopy(evidence.get(section)) for section in sections}
        packet['source_evidence_paths'] = [f'evidence.{s}' for s in sections]
        packets[specialist] = packet
    return packets

def build(source_path, output_dir):
    source_path, output_dir = Path(source_path), Path(output_dir)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    canonical = canonicalize(source)
    packets = make_packets(canonical)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in [('canonical_evidence.json',canonical)] + [(f'{k}_evidence.json',v) for k,v in packets.items()]:
        (output_dir/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (output_dir/'evidence_coverage.json').write_text(
        json.dumps(canonical['evidence_coverage'], ensure_ascii=False, indent=2), encoding='utf-8')
    return canonical, packets
