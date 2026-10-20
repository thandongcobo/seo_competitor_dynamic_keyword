"""Deterministic executive facts; model prose is not a source of measurements."""
from __future__ import annotations
import copy


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _metric(v):
    # Normalized Lighthouse metrics may be plain numbers or numericValue wrappers.
    if _number(v):
        return v
    if isinstance(v, dict):
        for k in ('numeric_value', 'numericValue', 'value'):
            if _number(v.get(k)):
                return v[k]
    return None


def _fact(packet, name):
    return next((f for f in packet.get('facts', []) if f.get('id') == name), None)


def structured_facts(packet):
    """Derive comparisons exclusively from verified values in the packet."""
    out = []
    ours, benchmark = packet['tracked'], packet['benchmark']
    if _number(ours.get('position')) and _number(benchmark.get('position')):
        out.append({'id': 'SERP_POSITION', 'kind': 'ranking',
                    'ours': ours['position'], 'benchmark': benchmark['position'],
                    'leader': 'ours' if ours['position'] < benchmark['position'] else
                              'benchmark' if ours['position'] > benchmark['position'] else 'tie'})
    lab = _fact(packet, 'TECH_LAB')
    if lab:
        values = lab.get('values') or {}
        for key, label in [('largest_contentful_paint_ms', 'LCP'),
                           ('total_blocking_time_ms', 'TBT')]:
            a = _metric(((values.get('ours') or {}).get('lab_metrics') or {}).get(key))
            b = _metric(((values.get('benchmark') or {}).get('lab_metrics') or {}).get(key))
            if a is not None and b is not None:
                out.append({'id': 'TECH_' + label, 'kind': 'lower_is_better',
                            'metric': key, 'ours': a, 'benchmark': b,
                            'better': 'ours' if a < b else 'benchmark' if a > b else 'tie',
                            'evidence_id': 'TECH_LAB'})
    title = _fact(packet, 'ON_TITLE')
    if title:
        match = (title.get('values') or {}).get('title_keyword_match') or {}
        if isinstance(match, dict) and isinstance(match.get('ours'), bool) and isinstance(match.get('competitor'), bool):
            out.append({'id': 'ON_TITLE_MATCH', 'kind': 'keyword_presence',
                        'ours': match['ours'], 'benchmark': match['competitor'], 'evidence_id': 'ON_TITLE'})
    for fact_id, section in [('BL_PAGE', 'page'), ('BL_DOMAIN', 'domain')]:
        fact = _fact(packet, fact_id)
        if fact:
            values = fact.get('values') or {}
            for metric in ('rank', 'referring_domains'):
                a = _metric((values.get('ours') or {}).get(metric)); b = _metric((values.get('benchmark') or {}).get(metric))
                if a is not None and b is not None:
                    out.append({'id': f'BL_{section.upper()}_{metric.upper()}', 'kind': 'backlink_metric', 'scope': section,
                                'metric': metric, 'ours': a, 'benchmark': b,
                                'leader': 'ours' if a > b else 'benchmark' if b > a else 'tie', 'evidence_id': fact_id})
    kw = _fact(packet, 'KW_SHARED')
    if kw:
        values = kw.get('values') or {}
        out.append({'id': 'KW_DOMAIN_CONTEXT', 'kind': 'domain_keyword_context',
                    'ours_ahead': values.get('generic_ours_ahead'), 'benchmark_ahead': values.get('generic_benchmark_ahead'),
                    'evidence_id': 'KW_SHARED'})
    return out


def publish_verified_response(response, packet):
    """Publish validated model explanations while retaining factual guardrails."""
    from .executive_synthesis import validate_executive
    result = copy.deepcopy(response)
    repairs = []
    errors = validate_executive(result, packet)
    if errors:
        # Only discard a complete claim when its evidence check fails. Schema or
        # source-reference errors remain fatal and cannot be silently repaired.
        from .executive_synthesis import SCHEMA
        from jsonschema import Draft202012Validator
        structural = [e.message for e in Draft202012Validator(SCHEMA).iter_errors(result)]
        if structural or any('Unknown evidence ID' in error for error in errors):
            raise ValueError('Executive response cannot be published: ' + '; '.join((structural or errors)[:4]))
        import re
        invalid_findings = {int(match.group(1)) for error in errors
            if (match := re.match(r'key_findings\[(\d+)\]', error))}
        invalid_decisions = {int(match.group(1)) for error in errors
            if (match := re.match(r'proposed_decisions\[(\d+)\]', error))}
        if any(error.startswith('executive_summary') for error in errors):
            tracked, benchmark = packet['tracked'], packet['benchmark']
            result['executive_summary'] = (
                f"In the saved results for '{packet.get('keyword')}', {tracked['domain']} appeared "
                f"at position {tracked['position']} and {benchmark['domain']} at position {benchmark['position']}. "
                'The measurements below identify issues to investigate; one saved search does not establish a ranking cause or trend.')
            result['executive_summary_evidence_ids'] = ['SERP']
            repairs.append('executive_summary: unsupported comparison removed')
        if invalid_findings:
            result['key_findings'] = [item for index, item in enumerate(result['key_findings']) if index not in invalid_findings]
            repairs.append(f'key_findings: removed {len(invalid_findings)} unsupported finding(s)')
        if invalid_decisions:
            result['proposed_decisions'] = [item for index, item in enumerate(result['proposed_decisions']) if index not in invalid_decisions]
            repairs.append(f'proposed_decisions: removed {len(invalid_decisions)} unsupported decision(s)')
        if not result['key_findings'] or validate_executive(result, packet):
            raise ValueError('Executive response still contains unsupported claims after filtering')
    for decision in result.get('proposed_decisions', []):
        if 'ON_TITLE' in decision.get('evidence_ids', []):
            check = decision.get('success_check', '')
            if 'approved' not in check.lower():
                decision['success_check'] = ('Verify the current title and search appearance; if a change is approved, '
                    'check its implementation and monitor the same queries over time. ' + check).strip()
                repairs.append('ON_TITLE success_check: verification and approval added')
        if 'TECH_INV' in decision.get('evidence_ids', []) and 'wdp.js' in decision.get('action','').lower():
            decision['action'] = ('Have engineering and fraud/security owners profile the cited scripts and bundles, '
                'confirm which changes preserve required controls, then test approved performance changes in comparable mobile runs.')
            repairs.append('TECH_INV action: required security controls protected')
        if 'ON_LINKS' in decision.get('evidence_ids', []) and 'implement internal links' in decision.get('action','').lower():
            decision['action'] = ('Audit links to the exact ranking page, distinguish navigation from relevant contextual links, '
                'then consider useful internal links where they help visitors find related content.')
            repairs.append('ON_LINKS action: link-quality review added')
    existing_ids = {id for item in result.get('key_findings', []) for id in item.get('evidence_ids', [])}
    backlink = _fact(packet, 'BL_PAGE')
    if backlink and 'BL_PAGE' not in existing_ids and len(result['key_findings']) < 8:
        values=backlink.get('values') or {}
        ours=(values.get('ours') or {}).get('rank'); other=(values.get('benchmark') or {}).get('rank')
        if _number(ours) and _number(other) and ours != other:
            stronger = packet['tracked']['domain'] if ours > other else packet['benchmark']['domain']
            result['key_findings'].append({
                'statement':f"Page-level backlink index: tracked {ours:g}, benchmark {other:g}; {stronger} has the higher provider score.",
                'interpretation':'This provider score compares the exact ranking pages, but does not measure the quality of individual linking pages.',
                'why_it_matters':'Relevant referring pages may help discovery and authority; the score alone cannot explain the saved ranking order.',
                'next_check':'Review the actual referring pages and domains for both ranking URLs, confirm relevance and link quality, then consider legitimate opportunities.',
                'evidence_ids':['BL_PAGE'],
                'limitation':'Third-party index score, not a Google ranking or proof of causation.'})
            repairs.append('BL_PAGE: source-grounded finding added for omitted evidence')
    content = _fact(packet, 'ON_CONTENT')
    if content and 'ON_CONTENT' not in existing_ids and len(result['key_findings']) < 8:
        values=content.get('values') or {}
        own_meta=str((values.get('ours') or {}).get('meta_description') or '')
        other_meta=str((values.get('benchmark') or {}).get('meta_description') or '')
        keyword=str(packet.get('keyword') or '').casefold()
        if keyword and own_meta and other_meta and keyword not in own_meta.casefold() and keyword in other_meta.casefold():
            result['key_findings'].append({
                'statement':f"The tracked page's saved meta description does not mention '{packet['keyword']}'; the benchmark's does.",
                'interpretation':'The captured descriptions emphasize different topics. Search engines may generate a different visible snippet.',
                'why_it_matters':'A clear description can help searchers judge whether the result matches their intent.',
                'next_check':'Check the current page description and displayed search snippet; draft a clearer version for approval if it better represents the page, then monitor clicks.',
                'evidence_ids':['ON_CONTENT'],
                'limitation':'Meta description wording is not a direct ranking boost; click impact is unverified.'})
            repairs.append('ON_CONTENT: source-grounded meta-description finding added')
    lab=_fact(packet,'TECH_LAB')
    if lab:
        values=lab.get('values') or {}
        for finding in result['key_findings']:
            if 'TECH_LAB' not in finding.get('evidence_ids',[]): continue
            for side in ('ours','benchmark'):
                metrics=(values.get(side) or {}).get('lab_metrics') or {}
                for metric in ('largest_contentful_paint_ms','total_blocking_time_ms'):
                    number=metrics.get(metric)
                    if _number(number):
                        for field in ('statement','interpretation','why_it_matters','next_check'):
                            text=finding.get(field,'')
                            exact=f'{number} ms'
                            if exact in text:
                                finding[field]=text.replace(exact,f'{number/1000:.1f} s')
                                repairs.append(f'{field}: lab milliseconds formatted as seconds')
    final_errors=validate_executive(result,packet)
    if final_errors:
        raise ValueError('Published report failed final validation: '+'; '.join(final_errors[:4]))
    return result, repairs




def _explanations(facts, packet):
    rows = []
    if 'ON_TITLE_MATCH' in facts and facts['ON_TITLE_MATCH']['ours'] != facts['ON_TITLE_MATCH']['benchmark']:
        rows.append({'title':'Aviator targeting differs in the HTML title','explanation':'The benchmark page explicitly includes the target keyword in its title while the tracked page does not.','evidence_ids':['ON_TITLE'],'counterevidence':'Title wording alone does not determine ranking.','why_it_might_matter':'It may provide clearer relevance signalling and improve search-result clarity.','unverified':'Intent fit and any ranking effect require verification after an approved change.'})
    if 'BL_PAGE_RANK' in facts:
        f=facts['BL_PAGE_RANK']; rows.append({'title':'Page-specific authority may differ','explanation':'The measured backlink rank for the two exact ranking pages differs.','evidence_ids':['BL_PAGE'],'counterevidence':'Domain-wide metrics may point in the opposite direction.','why_it_might_matter':'Links pointing to the exact page may support discovery and authority, but quality and relevance are unknown.','unverified':'Individual referring-page quality and causation.'})
    if 'TECH_LCP' in facts:
        rows.append({'title':'The tracked page has slower observed LCP','explanation':'The saved mobile lab run measured slower LCP for Hollywoodbets.','evidence_ids':['TECH_LAB'],'counterevidence':'Hollywoodbets has better observed TBT in the same run.','why_it_might_matter':'A slower first meaningful experience may warrant engineering investigation.','unverified':'Field performance and ranking impact.'})
    return rows[:4]


def _strengths(facts):
    out=[]
    if facts.get('TECH_TBT',{}).get('better')=='ours': out.append({'statement':'Hollywoodbets has the better measured TBT in the saved mobile Lighthouse run.','evidence_ids':['TECH_LAB']})
    if facts.get('BL_DOMAIN_RANK',{}).get('leader')=='ours': out.append({'statement':'Hollywoodbets has the stronger measured domain-wide backlink rank.','evidence_ids':['BL_DOMAIN']})
    return out


def _opportunities(facts):
    out=[]
    for x in _explanations(facts, {}): out.append({'statement':x['title']+'.','evidence_ids':x['evidence_ids'],'limitation':x['unverified']})
    return out


def _improvements(facts):
    out=[]
    if 'ON_TITLE_MATCH' in facts and facts['ON_TITLE_MATCH']['ours'] != facts['ON_TITLE_MATCH']['benchmark']:
        out.append({'action':'Verify the current Aviator title and prepare an accurate revision for approval if it better matches page intent.','reason':'The saved ranking pages differ in target-keyword title presence.','owner':'Content / SEO','dependencies':'Rendered HTML and search appearance review.','validation':'Recrawl the exact URL and monitor the saved target query over time.','evidence_ids':['ON_TITLE']})
    if 'BL_PAGE_RANK' in facts:
        out.append({'action':'Audit the quality, relevance and placement of links pointing to both exact ranking pages, then identify legitimate page-specific opportunities.','reason':'Page-level backlink measurements differ.','owner':'SEO','dependencies':'Referring-page review and link policy.','validation':'Recheck page-level referring domains after approved work.','evidence_ids':['BL_PAGE']})
    if 'TECH_LCP' in facts:
        out.append({'action':'Profile the resources and rendering bottlenecks identified by Lighthouse while preserving security and fraud-prevention controls.','reason':'Hollywoodbets has slower observed LCP but better TBT, so the bottleneck needs targeted investigation.','owner':'Engineering','dependencies':'Controlled mobile lab reruns and release approval.','validation':'Repeat comparable Lighthouse runs and, when available, review field data.','evidence_ids':['TECH_LAB','TECH_INV']})
    return out[:3]
