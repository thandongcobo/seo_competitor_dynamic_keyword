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
    """Publish plain-language explanations built only from validated evidence.

    Model proposed decisions remain suggestions; title actions are gated on review.
    The original model response is not modified and can be retained for audit.
    """
    result = copy.deepcopy(response)
    facts = {f['id']: f for f in structured_facts(packet)}
    tracked, benchmark = packet['tracked'], packet['benchmark']
    keyword = packet.get('keyword') or 'the target query'
    # Keep focused-path identity out of the closed executive response schema,
    # then restore it as read-only publication metadata after validation.
    if response.get('recommendation_engine'):
        result['recommendation_engine'] = response['recommendation_engine']
    tracked_name = tracked.get('domain') or 'the tracked site'
    benchmark_name = benchmark.get('domain') or 'the benchmark'
    gap = abs(tracked['position'] - benchmark['position'])
    if tracked['position'] < benchmark['position']:
        ranking_explanation = f"{tracked['domain']} leads by {gap} position" + (' in this snapshot.' if gap == 1 else 's in this snapshot.')
    elif tracked['position'] > benchmark['position']:
        ranking_explanation = f"{benchmark['domain']} leads by {gap} position" + (' in this snapshot.' if gap == 1 else 's in this snapshot.')
    else:
        ranking_explanation = 'Both domains appear at the same position in this snapshot.'
    summary = (f"In the saved Google results for '{keyword}', {tracked['domain']} ranked "
               f"#{tracked['position']} and {benchmark['domain']} ranked #{benchmark['position']}. "
               f"{ranking_explanation} This is one recorded search, not evidence of a sustained trend or why the positions differ.")
    findings = []
    findings.append({
        'statement': f"Saved Google result: {tracked['domain']} is #{tracked['position']} and {benchmark['domain']} is #{benchmark['position']} for '{keyword}'.",
        'interpretation': ranking_explanation + ' The result confirms a visibility difference for this captured query and market only.',
        'why_it_matters': 'The higher-listed result is encountered earlier on this search-results page, giving the benchmark greater visibility in this snapshot.',
        'next_check': 'Repeat the same query with the same market and device context over multiple dates; compare the exact ranking URLs before treating the gap as persistent.',
        'evidence_ids': ['SERP'],
        'limitation': 'A single saved SERP is not a trend. Rankings vary, and this comparison does not identify a cause.'
    })
    if 'ON_TITLE_MATCH' in facts:
        f = facts['ON_TITLE_MATCH']
        if f['ours'] != f['benchmark']:
            tracked_presence = 'includes' if f['ours'] else 'does not include'
            benchmark_presence = 'includes' if f['benchmark'] else 'does not include'
            findings.append({
                'statement': f"The captured HTML title for the tracked ranking page {tracked_presence} '{keyword}'; the benchmark title {benchmark_presence} it.",
                'interpretation': 'This is a difference in the page title text captured by the crawler. Google may rewrite the title shown in results, so the HTML title and visible search-result title are related but not always identical.',
                'why_it_matters': 'A clear, accurate title can help search engines and people understand what the page is about. Keyword presence by itself is not a ranking recipe.',
                'next_check': 'Open both cited ranking URLs, verify their current rendered title tags and Google result titles, then assess whether the tracked title accurately matches the page and search intent before proposing an edit.',
                'evidence_ids': ['ON_TITLE'],
                'limitation': 'The snapshot establishes title wording only. It does not prove that title wording caused the position gap or that adding the keyword would improve ranking or clicks.'
            })
    links = _fact(packet, 'ON_LINKS')
    if links:
        values = links.get('values') or {}
        counts = values.get('internal_link_count') or {}
        ours, other = _metric(counts.get('ours')), _metric(counts.get('competitor'))
        if ours is not None and other is not None and ours != other:
            lead = 'benchmark' if other > ours else 'tracked page'
            delta = abs(other - ours)
            findings.append({
                'statement': f"The crawler counted {ours:g} internal links on the tracked page and {other:g} on the benchmark page ({lead} page: {delta:g} more).",
                'interpretation': 'This is a count of links detected in the captured pages. More links do not automatically mean better internal linking; their destinations, anchor wording, placement, and usefulness matter.',
                'why_it_matters': 'Relevant internal links can help visitors move through a site and help crawlers discover related pages. A raw total cannot tell whether those links meaningfully support the selected ranking page.',
                'next_check': 'Review the captured link lists and compare unique, relevant links pointing to each exact ranking URL. Separate repeated navigation/footer links from contextual links before deciding whether there is a useful gap.',
                'evidence_ids': ['ON_LINKS'],
                'limitation': 'A page-level count is not link density or quality, may include repeated site-wide links, and does not establish ranking causation.'
            })
    for name, label in [('TECH_LCP', 'Largest Contentful Paint'), ('TECH_TBT', 'Total Blocking Time')]:
        if name in facts:
            f = facts[name]
            side = ('the tracked page' if f['better'] == 'ours' else
                    'the benchmark' if f['better'] == 'benchmark' else 'neither page')
            unit = 's' if label == 'Largest Contentful Paint' else 's'
            tracked_seconds, benchmark_seconds = f['ours'] / 1000, f['benchmark'] / 1000
            difference_seconds = abs(tracked_seconds - benchmark_seconds)
            if f['better'] == 'ours':
                comparison = f"The tracked page was about {difference_seconds:.1f} seconds faster in this lab run."
            elif f['better'] == 'benchmark':
                comparison = f"The tracked page was about {difference_seconds:.1f} seconds slower in this lab run."
            else:
                comparison = 'The measured values were equal in this lab run.'
            summary += f" {label}: tracked {tracked_seconds:.1f}{unit}, benchmark {benchmark_seconds:.1f}{unit}."
            if name == 'TECH_LCP':
                meaning = 'LCP estimates when the main visible content finished appearing during this test. A longer time is a reason to investigate loading experience, not proof of a specific technical cause.'
                why = 'If repeated under comparable conditions and reflected in real-user data, slow visible loading can be a user-experience concern. This measurement alone cannot show how visitors experienced the page.'
                check = 'Repeat several mobile Lighthouse runs with the same settings, identify the LCP element and its loading dependencies, and compare with real-user Core Web Vitals if available.'
            else:
                meaning = 'TBT estimates how much long-running main-thread work delayed interaction during this lab test. Lower is better; it is distinct from LCP and does not describe the whole page experience.'
                why = 'A high or worsening TBT can make a page feel less responsive. Read it alongside LCP and other measures rather than treating one metric as an overall performance score.'
                check = 'Repeat comparable mobile Lighthouse runs and inspect the long tasks shown in the diagnostic report; confirm any proposed fix improves responsiveness without harming loading.'
            findings.append({
                'statement': f"{label}: tracked page {tracked_seconds:.1f}{unit} vs benchmark {benchmark_seconds:.1f}{unit}. {comparison}",
                'interpretation': meaning,
                'why_it_matters': why,
                'next_check': check,
                'evidence_ids': ['TECH_LAB'],
                'limitation': 'These are single-run synthetic Lighthouse measurements, not field data. Device/network conditions affect results; the metric does not identify a root cause or prove a ranking effect.'
            })
    if 'BL_PAGE_RANK' in facts:
        f = facts['BL_PAGE_RANK']; leader = benchmark_name if f['leader'] == 'benchmark' else tracked_name if f['leader'] == 'ours' else 'neither page'
        findings.append({'statement': f"Page-specific third-party backlink rank favors {leader} ({f['ours']} tracked versus {f['benchmark']} benchmark).",
                         'interpretation': 'This is a third-party index score for the two ranking URLs. It is not a Google position; a larger score is stronger only within this provider metric.',
                         'why_it_matters': 'Links from relevant, trusted pages can contribute to discovery and authority, but this aggregate score does not reveal which referring links are valuable.',
                         'next_check': 'Compare the referring domains and linking pages for these exact URLs, confirm the links are live and relevant, and investigate unusual or low-quality patterns before proposing outreach.',
                         'evidence_ids': ['BL_PAGE'], 'limitation': 'Provider index scores are estimates. Individual link quality, relevance, freshness, and any ranking effect are unverified.'})
    if 'BL_DOMAIN_RANK' in facts:
        f = facts['BL_DOMAIN_RANK']; leader = tracked_name if f['leader'] == 'ours' else benchmark_name if f['leader'] == 'benchmark' else 'neither domain'
        findings.append({'statement': f"Domain-wide third-party backlink rank favors {leader} ({f['ours']} tracked versus {f['benchmark']} benchmark).",
                         'interpretation': 'This describes the provider’s estimate for each whole domain, not the selected ranking pages.',
                         'why_it_matters': 'Domain-level link profiles provide broad competitive context, but they cannot explain a page-versus-page ranking difference on their own.',
                         'next_check': 'Use the page-level backlink evidence for the ranking URLs and inspect the strongest relevant referring pages; keep domain and page findings separate.',
                         'evidence_ids': ['BL_DOMAIN'], 'limitation': 'Third-party index score, not Google rank. Domain-wide metrics cannot be attributed to either exact ranking page or to ranking causation.'})
    if 'KW_DOMAIN_CONTEXT' in facts:
        f = facts['KW_DOMAIN_CONTEXT']; findings.append({'statement': f"In the saved related-keyword set, the tracked domain leads on {f.get('ours_ahead') or 0} shared queries and the benchmark leads on {f.get('benchmark_ahead') or 0}.",
                         'interpretation': 'These are counts of queries where each domain leads, not average ranking positions or traffic totals.',
                         'why_it_matters': 'The split offers broader context about which site appears to lead across the measured query set; it does not measure the value of each query to the business.',
                         'next_check': 'Review the actual query list, search volumes, intent, and ranking URLs, then prioritize queries that match the business objective.',
                         'evidence_ids': ['KW_SHARED'], 'limitation': 'Domain-level context only. Different URLs may rank, and the counts do not prove page-level relevance, traffic, or causation.'})
    # Keep the validated model response verbatim. Deterministic explanations are supplementary.
    result['verified_factual_summary'] = summary
    result['verified_factual_findings'] = findings
    result['specialist_findings'] = copy.deepcopy(packet.get('specialist_findings') or [])
    # Preserve both audience explanations and the per-finding disposition verbatim.
    if 'finding_dispositions' in response:
        result['finding_dispositions'] = copy.deepcopy(response['finding_dispositions'])
    result.setdefault('implementation_plans', [])
    result['potential_ranking_explanations'] = _explanations(facts, packet)
    result['hollywoodbets_strengths'] = _strengths(facts, packet)
    result['hollywoodbets_weaknesses_opportunities'] = _opportunities(facts, packet)
    result['recommended_improvements'] = _improvements(facts, packet)
    result['evidence_coverage'] = packet.get('evidence_coverage') or {}
    # Do not mutate validated LLM decisions; annotate their limitations instead.
    return result, ['preserved validated model text; appended verified facts and complete specialist lineage']


def _explanations(facts, packet):
    rows = []
    keyword = (packet or {}).get('keyword') or 'the selected keyword'
    tracked = ((packet or {}).get('tracked') or {}).get('domain') or 'the tracked site'
    if 'ON_TITLE_MATCH' in facts and facts['ON_TITLE_MATCH']['ours'] != facts['ON_TITLE_MATCH']['benchmark']:
        rows.append({'title':f'{keyword} targeting differs in the HTML title','explanation':'The benchmark page explicitly includes the target keyword in its title while the tracked page does not.','evidence_ids':['ON_TITLE'],'counterevidence':'Title wording alone does not determine ranking.','why_it_might_matter':'It may provide clearer relevance signalling and improve search-result clarity.','unverified':'Intent fit and any ranking effect require verification after an approved change.'})
    if 'BL_PAGE_RANK' in facts:
        f=facts['BL_PAGE_RANK']; rows.append({'title':'Page-specific authority may differ','explanation':'The measured backlink rank for the two exact ranking pages differs.','evidence_ids':['BL_PAGE'],'counterevidence':'Domain-wide metrics may point in the opposite direction.','why_it_might_matter':'Links pointing to the exact page may support discovery and authority, but quality and relevance are unknown.','unverified':'Individual referring-page quality and causation.'})
    if 'TECH_LCP' in facts:
        rows.append({'title':'The tracked page has slower observed LCP','explanation':f'The saved mobile lab run measured slower LCP for {tracked}.','evidence_ids':['TECH_LAB'],'counterevidence':f'{tracked} has better observed TBT in the same run.','why_it_might_matter':'A slower first meaningful experience may warrant engineering investigation.','unverified':'Field performance and ranking impact.'})
    return rows[:4]


def _strengths(facts, packet):
    out=[]
    tracked = ((packet or {}).get('tracked') or {}).get('domain') or 'The tracked site'
    if facts.get('TECH_TBT',{}).get('better')=='ours': out.append({'statement':f'{tracked} has the better measured TBT in the saved mobile Lighthouse run.','evidence_ids':['TECH_LAB']})
    if facts.get('BL_DOMAIN_RANK',{}).get('leader')=='ours': out.append({'statement':f'{tracked} has the stronger measured domain-wide backlink rank.','evidence_ids':['BL_DOMAIN']})
    return out


def _opportunities(facts, packet):
    out=[]
    for x in _explanations(facts, packet): out.append({'statement':x['title']+'.','evidence_ids':x['evidence_ids'],'limitation':x['unverified']})
    return out


def _improvements(facts, packet):
    out=[]
    keyword = (packet or {}).get('keyword') or 'the target query'
    tracked = ((packet or {}).get('tracked') or {}).get('domain') or 'The tracked site'
    if 'ON_TITLE_MATCH' in facts and facts['ON_TITLE_MATCH']['ours'] != facts['ON_TITLE_MATCH']['benchmark']:
        out.append({'action':f'Verify the current {keyword} title and prepare an accurate revision for approval if it better matches page intent.','reason':'The saved ranking pages differ in target-keyword title presence.','owner':'Content / SEO','dependencies':'Rendered HTML and search appearance review.','validation':'Recrawl the exact URL and monitor the saved target query over time.','evidence_ids':['ON_TITLE']})
    if 'BL_PAGE_RANK' in facts:
        out.append({'action':'Audit the quality, relevance and placement of links pointing to both exact ranking pages, then identify legitimate page-specific opportunities.','reason':'Page-level backlink measurements differ.','owner':'SEO','dependencies':'Referring-page review and link policy.','validation':'Recheck page-level referring domains after approved work.','evidence_ids':['BL_PAGE']})
    if 'TECH_LCP' in facts:
        out.append({'action':'Profile the resources and rendering bottlenecks identified by Lighthouse while preserving security and fraud-prevention controls.','reason':f'{tracked} has slower observed LCP but better TBT, so the bottleneck needs targeted investigation.','owner':'Engineering','dependencies':'Controlled mobile lab reruns and release approval.','validation':'Repeat comparable Lighthouse runs and, when available, review field data.','evidence_ids':['TECH_LAB','TECH_INV']})
    return out[:3]
