"""Auditable SEO recommendations, with conservative triage rather than rank forecasts."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from analysis.recommendation_classification import (
    TIER_1, TIER_2, adapt_recommendations,
)

from analysis.advanced_evidence import classify_opportunity_relevance


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _host(url):
    try:
        return (urlsplit(url).hostname or '').lower().removeprefix('www.')
    except (TypeError, ValueError):
        return ''


def _same_site(url, reference):
    host, base = _host(url), _host(reference)
    return bool(host and base and (host == base or host.endswith('.' + base)))


def _normalized_page(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            return None
        return (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/') or '/')
    except (TypeError, ValueError):
        return None


def _stable_token(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:10]


def _resource_topic_matches(url, headings, keyword):
    path_tokens = set(re.findall(r'[a-z0-9]+', urlsplit(url).path.casefold()))
    labels = [str(row.get('text') or '').strip() for row in headings
              if isinstance(row, dict) and str(row.get('text') or '').strip()]
    heading_tokens = set(re.findall(r'[a-z0-9]+', ' '.join(labels).casefold()))
    keyword_tokens = set(re.findall(r'[a-z0-9]+', (keyword or '').casefold()))
    stop = {'the', 'and', 'with', 'from', 'your', 'our', 'for', 'into', 'page', 'more'}
    # Plural folding is limited to path/heading token matching, never factual text.
    def stems(tokens):
        return {token[:-1] if len(token) > 4 and token.endswith('s') else token for token in tokens}
    path_tokens = stems(path_tokens - stop)
    heading_tokens = stems(heading_tokens - stop)
    keyword_tokens = stems(keyword_tokens - stop)
    if not (path_tokens & heading_tokens) or not (path_tokens & (heading_tokens | keyword_tokens)):
        return []
    return [label for label in labels
            if path_tokens & stems(set(re.findall(r'[a-z0-9]+', label.casefold())) - stop)]


def _enriched_rows(evidence, kind, side=None):
    return [row for row in (evidence or []) if isinstance(row, dict)
            and row.get('metric_or_observation') == kind
            and (side is None or (row.get('page') or {}).get('side') == side)]


def _identity_enriched_rows(evidence, kind, *, side, target_url, keyword):
    """Use enrichment only when keyword, side, exact URL, scope and hash agree."""
    rows = []
    for row in _enriched_rows(evidence, kind, side):
        page = row.get('page') or {}
        provenance = row.get('provenance') or {}
        if (str(row.get('keyword') or '').casefold() != str(keyword).casefold()
                or _normalized_page(page.get('url')) != _normalized_page(target_url)
                or row.get('scope') != 'page'
                or not row.get('evidence_id')
                or not provenance.get('source_sha256')):
            continue
        rows.append(row)
    return rows


_COPY_STOP = {'a', 'an', 'and', 'at', 'by', 'for', 'from', 'in', 'into', 'of', 'on', 'or',
              'the', 'to', 'with', 'your', 'our', 'this', 'that'}
_COPY_CONNECTORS = {'about', 'learn', 'explore', 'review', 'information', 'including', 'page'}


def _copy_tokens(value):
    return {token for token in re.findall(r'[a-z0-9]+', str(value or '').casefold())
            if len(token) > 1 and token not in _COPY_STOP}


def _page_copy_context(evidence, *, target_url, keyword):
    metadata_rows = _identity_enriched_rows(evidence, 'page_metadata_and_rendering',
        side='ours', target_url=target_url, keyword=keyword)
    heading_rows = _identity_enriched_rows(evidence, 'rendered_heading_inventory',
        side='ours', target_url=target_url, keyword=keyword)
    passage_rows = _identity_enriched_rows(evidence, 'keyword_relevant_visible_passages',
        side='ours', target_url=target_url, keyword=keyword)
    metadata_row = metadata_rows[0] if metadata_rows else None
    meta = metadata_row.get('value') if metadata_row and isinstance(metadata_row.get('value'), dict) else {}
    headings = []
    for row in heading_rows:
        if isinstance(row.get('value'), list):
            headings.extend(item for item in row['value'] if isinstance(item, dict) and item.get('text'))
    passages = []
    for row in passage_rows:
        if isinstance(row.get('value'), list):
            passages.extend(str(item.get('text')) for item in row['value']
                            if isinstance(item, dict) and item.get('text'))
    return {'metadata': meta, 'metadata_row': metadata_row, 'headings': headings,
            'heading_rows': heading_rows, 'passages': passages,
            'passage_rows': passage_rows,
            'evidence_ids': [row['evidence_id'] for row in
                ([metadata_row] if metadata_row else []) + heading_rows + passage_rows]}


def _reliable_page_context(context):
    metadata = context.get('metadata') or {}
    return (metadata.get('status_code') == 200
            and metadata.get('extraction_status') == 'complete'
            and metadata.get('url_alignment') == 'matched'
            and metadata.get('robots') is not None)


def _heading_texts(context, level):
    return [str(row.get('text')).strip() for row in context.get('headings', [])
            if row.get('level') == level and str(row.get('text') or '').strip()]


def _page_brand_from_title(title, target_url):
    parts = [part.strip() for part in str(title or '').split('|') if part.strip()]
    if len(parts) < 2:
        return ''
    candidate = parts[-1]
    host_tokens = _copy_tokens(_host(target_url).replace('.', ' '))
    brand_tokens = _copy_tokens(candidate)
    return candidate if brand_tokens and brand_tokens.issubset(host_tokens) else ''


def _topic_heading(context, keyword):
    core = _copy_tokens(keyword)
    if not core:
        return ''
    h1s = _heading_texts(context, 'h1')
    headings = h1s + _heading_texts(context, 'h2') + _heading_texts(context, 'h3')
    for heading in headings:
        tokens = _copy_tokens(heading)
        if core.issubset(tokens):
            return heading
    return ''


def _grounded_copy(candidate, evidence_text, *, generic_words=()):
    allowed = _copy_tokens(evidence_text) | _COPY_CONNECTORS | _copy_tokens(generic_words)
    unsupported = sorted(_copy_tokens(candidate) - allowed)
    return {'grounded': not unsupported, 'unsupported_tokens': unsupported}


def _compose_title_candidate(keyword, target_url, context, competitor_title=''):
    if not _reliable_page_context(context):
        return None
    metadata = context['metadata']
    topic = _topic_heading(context, keyword)
    if not topic:
        return None
    h1 = _heading_texts(context, 'h1')
    support = ''
    for heading in _heading_texts(context, 'h2'):
        if not _copy_tokens(keyword).issubset(_copy_tokens(heading)):
            continue
        if re.match(r'\s*(?:how\s+to|guide\b|overview\b|what\s+is\b|explained\b)', heading, re.I):
            support = re.sub(re.escape(keyword), '', heading, flags=re.I).strip(' :-|')
            support = re.sub(r'\b(?:a|an|the)\s*$', '', support, flags=re.I).strip()
            if support:
                break
    display_topic = topic.title()
    candidate = f'{display_topic}: {support.title()}' if support else display_topic
    brand = _page_brand_from_title(metadata.get('title'), target_url)
    if brand:
        candidate += f' | {brand}'
    if len(candidate) > 65 and support:
        candidate = f'{display_topic} | {brand}' if brand else display_topic
    current = str(metadata.get('title') or '').strip()
    if not current or candidate.casefold() == current.casefold() or candidate.casefold() == str(competitor_title).strip().casefold():
        return None
    source = ' '.join([current, *h1, *[str(x.get('text')) for x in context.get('headings', [])],
                       *context.get('passages', [])])
    validation = _grounded_copy(candidate, source)
    if not validation['grounded']:
        return None
    return {'field': 'title', 'candidate': candidate, 'status': 'proposed_not_observed',
            'replaces_observed': current, 'basis': [f'Captured H1: {h1[0]}' if h1 else f'Captured page heading: {topic}'] +
                ([f'Captured supporting section: {next(h for h in _heading_texts(context, "h2") if support.casefold() in h.casefold())}'] if support else []),
            'source_evidence_ids': context['evidence_ids'], 'validation': validation}


def _compact_section_heading(heading, keyword, brand=''):
    text = re.sub(re.escape(keyword), '', str(heading), flags=re.I).strip(' :-|')
    if brand:
        text = re.sub(re.escape(brand), '', text, flags=re.I).strip(' :-|')
    text = re.sub(r'\s+that\s+.*$', '', text, flags=re.I).strip()
    text = re.sub(r'\s+with\s+.*$', '', text, flags=re.I).strip()
    text = re.sub(r'\b(?:a|an|the)\s*$', '', text, flags=re.I).strip()
    if re.match(r'how\s+to\b', text, re.I):
        return re.sub(r'\s+', ' ', text).lower()
    return re.sub(r'\s+', ' ', text).lower()


def _compose_meta_candidate(keyword, target_url, context):
    if not _reliable_page_context(context) or not context.get('passages'):
        return None
    metadata = context['metadata']
    topic = _topic_heading(context, keyword)
    if not topic or not any(_copy_tokens(keyword).issubset(_copy_tokens(passage))
                            for passage in context.get('passages', [])):
        return None
    ranked_sections = []
    for level in ('h2', 'h3'):
        for heading in _heading_texts(context, level):
            if _copy_tokens(keyword).issubset(_copy_tokens(heading)):
                compact = _compact_section_heading(heading, keyword,
                    _page_brand_from_title(metadata.get('title'), target_url))
            else:
                compact = re.sub(r'\s+that\s+.*$', '', heading, flags=re.I).strip().lower()
                brand = _page_brand_from_title(metadata.get('title'), target_url)
                if brand:
                    compact = re.sub(re.escape(brand), '', compact, flags=re.I).strip(' :-|')
            if not compact or compact.casefold() == topic.casefold():
                continue
            compact_tokens = _copy_tokens(compact)
            if not compact_tokens or compact_tokens.issubset(_COPY_STOP | {'why', 'try', 'other', 'our', 'with'}):
                continue
            weight = 0 if re.search(r'how\s+to|guide|overview|explained|feature|payment|fair|rule|mechanic|payout', compact, re.I) else 1
            ranked_sections.append((weight, len(ranked_sections), compact))
    sections = []
    for _, _, compact in sorted(ranked_sections):
        if compact.casefold() not in {x.casefold() for x in sections}:
            sections.append(compact)
        if len(sections) == 4:
            break
    if len(sections) < 2:
        return None
    brand = _page_brand_from_title(metadata.get('title'), target_url)
    candidate = f"Learn about {topic.title()}: {', '.join(sections[:-1])} and {sections[-1]}"
    if brand:
        candidate += f' on {brand}'
    candidate += '.'
    if len(candidate) > 160:
        candidate = f"Learn about {topic.title()}: {', '.join(sections[:2])}"
        if brand:
            candidate += f' on {brand}'
        candidate += '.'
    current = str(metadata.get('meta_description') or '').strip()
    if not current or candidate.casefold() == current.casefold():
        return None
    source = ' '.join([current, topic, *sections, *[str(x.get('text')) for x in context.get('headings', [])],
                       *context.get('passages', [])])
    validation = _grounded_copy(candidate, source)
    if not validation['grounded']:
        return None
    return {'field': 'meta_description', 'candidate': candidate, 'status': 'proposed_not_observed',
            'replaces_observed': current, 'basis': [f'Captured page topic: {topic}',
                'Captured visible section headings and keyword-relevant page text'],
            'source_evidence_ids': context['evidence_ids'], 'validation': validation}


def _resource_name(url):
    try:
        parsed = urlsplit(url)
        return parsed.path.rstrip('/').split('/')[-1] or parsed.hostname or 'unnamed resource'
    except (TypeError, ValueError):
        return 'unnamed resource'


def _resource_ownership(url, target_url):
    return 'same-site-host' if _same_site(url, target_url) else 'third-party-host'


def _format_resource_action(resource, target_url):
    url = resource.get('url')
    if not url:
        return None
    name = _resource_name(url)
    ownership = _resource_ownership(url, target_url)
    metrics = []
    wasted = resource.get('wastedBytes')
    if _num(wasted) and wasted > 0:
        metrics.append(f"about {wasted / 1024:.0f} KiB flagged as potentially unused")
    wasted_ms = resource.get('wastedMs')
    if _num(wasted_ms) and wasted_ms > 0:
        metrics.append(f"{wasted_ms:.0f} ms estimated opportunity in this lab run")
    total = resource.get('total')
    if _num(total) and total > 0:
        metrics.append(f"{total:.0f} ms of measured work in this lab run")
    detail = f" ({'; '.join(metrics)})" if metrics else ''
    return {'url': url, 'name': name, 'ownership': ownership,
            'description': f'{name} [{ownership}{detail}]'}


def _compose_technical_action(areas, resources, target_url):
    details = [_format_resource_action(row, target_url) for row in resources]
    details = [row for row in details if row]
    if not details:
        return None
    names = '; '.join(row['description'] for row in details)
    third_party = [row['name'] for row in details if row['ownership'] == 'third-party-host']
    has_js = bool({'javascript_execution', 'unused_javascript'} & set(areas))
    has_image = 'image_delivery' in areas
    has_render = 'render_blocking' in areas
    steps = [f"On {target_url}, review the Lighthouse-identified resources: {names}."]
    if has_js:
        steps.append('For same-site resources, use script coverage, source maps and a recorded primary journey to locate work that is unnecessary before interaction. Split, tree-shake or defer only code proven non-critical; verify bundle ownership and preserve required functionality.')
    if has_image:
        steps.append('Compare each image’s intrinsic dimensions with its rendered size and responsive variants. Resize or convert through the existing asset pipeline only when the delivered file is larger than required; preserve visual quality and verify the selected responsive source.')
    if has_render:
        steps.append('For render-blocking resources, confirm ownership and dependency in the critical rendering path before changing loading order. Adjust priority or defer only after testing layout and the primary journey.')
    if third_party:
        steps.append('Third-party resources require owner/vendor review before any change. Do not edit, defer or remove them until their security, fraud-prevention, payment, consent and essential-function roles are verified and an approved safe configuration is available.')
    steps.append('Repeat the same mobile Lighthouse run, compare the same diagnostic and resource, then test the primary user journey and browser errors. Lab savings are estimates, not promised outcomes.')
    return ' '.join(steps), details


def _merge_overlapping_javascript_actions(results, target_url):
    """Coalesce the execution/unused-code cards when they target the same file."""
    execution = next((row for row in results if row.get('id') == 'technical-mobile-javascript_execution'), None)
    unused = next((row for row in results if row.get('id') == 'technical-mobile-unused_javascript'), None)
    if not execution or not unused:
        return results
    execution_resources = execution.get('evidence_provenance', {}).get('resource_candidates') or []
    unused_resources = unused.get('evidence_provenance', {}).get('resource_candidates') or []
    execution_urls = {_normalized_page(row.get('url')) for row in execution_resources if row.get('url')}
    unused_urls = {_normalized_page(row.get('url')) for row in unused_resources if row.get('url')}
    overlap = execution_urls & unused_urls
    if not overlap:
        return results
    combined = []
    seen = set()
    for resource in execution_resources + unused_resources:
        key = _normalized_page(resource.get('url')) if isinstance(resource, dict) else None
        if key and key not in seen:
            combined.append(resource)
            seen.add(key)
    action = _compose_technical_action({'javascript_execution', 'unused_javascript'}, combined, target_url)
    if not action:
        return results
    action_text, resource_details = action
    execution['title'] = 'Reduce JavaScript work on the tracked page'
    execution['evidence'] = ('The saved mobile Lighthouse run flagged JavaScript execution and potentially unused code. '
        'At least one resource appears in both diagnostics; exact resources and measurements are in the technical appendix.')
    execution['interpretation'] = ('Profiling and trimming only verified non-critical work may improve loading responsiveness. '
        'This single lab run does not establish field performance or ranking causation.')
    execution['actions'] = [action_text]
    display_names = ', '.join(row['name'] for row in resource_details)
    execution['display_action'] = (f"On the tracked page, profile {display_names}. Optimize same-site code only after coverage confirms it is non-critical; have the owner review third-party code, and preserve security and essential functionality. Re-run the same Lighthouse test and primary journey.")
    provenance = execution.setdefault('evidence_provenance', {})
    provenance['resource_candidates'] = combined
    provenance['diagnostic_areas'] = ['javascript_execution', 'unused_javascript']
    provenance['overlapping_resource_urls'] = [row.get('url') for row in combined
        if _normalized_page(row.get('url')) in overlap]
    execution['coalesced_recommendations'] = [execution['id'], unused['id']]
    execution['action_composition'] = {'status': 'specific_resource_action_coalesced_overlapping_diagnostics',
        'specificity': 'resource names, host ownership class, measured diagnostic and safety checks included',
        'resource_names': display_names.split(', '),
        'third_party_resources_require_owner_review': any(row['ownership'] == 'third-party-host' for row in resource_details)}
    return [row for row in results if row is not unused]


def build_recommendation_evidence_audit(*, keyword, ranking_urls, advanced_evidence,
                                       enriched_page_evidence=None):
    """Keep incomplete candidate signals visible without promoting them to plans."""
    ours_url = (ranking_urls or {}).get('ours')
    benchmark_url = (ranking_urls or {}).get('benchmark')
    page_links = _enriched_rows(enriched_page_evidence, 'outgoing_internal_link_inventory')
    benchmark_links = [item.get('destination_url') for row in page_links
                       if (row.get('page') or {}).get('side') == 'benchmark'
                       for item in row.get('value', []) if isinstance(item, dict)]
    keyword_rows = ((advanced_evidence or {}).get('keyword_intersection') or {}).get('related_generic_queries') or []
    has_question_queries = any(
        isinstance(row, dict) and re.search(r'\b(?:faq|question|questions)\b', str(row.get('keyword') or ''), re.I)
        for row in keyword_rows)
    withheld = []
    if any(re.search(r'faq|frequently-asked|questions', urlsplit(url).path, re.I)
           for url in benchmark_links if isinstance(url, str)) and not has_question_queries:
        withheld.append({
            'candidate': 'FAQ or common-question content', 'status': 'withheld_incomplete_observation',
            'source_url': benchmark_url,
            'reason': 'The saved benchmark page links to an FAQ-like destination, but the question content and query-level question demand are not available. A competitor link alone does not establish a first-party content gap.',
            'next_evidence_needed': 'Captured relevant question queries or first-party Search Console/PAA evidence, plus current content from the exact candidate page.',
        })
    backlinks = ((advanced_evidence or {}).get('backlinks') or {}).get('page') or {}
    if backlinks and not backlinks.get('referring_domains_list'):
        withheld.append({
            'candidate': 'Specific editorial backlink prospects', 'status': 'withheld_incomplete_observation',
            'source_url': ours_url,
            'reason': 'Saved page-level backlink data contains aggregate counts, not referring-page examples or editorial context. No acquisition targets are recommended.',
            'next_evidence_needed': 'A saved, URL-scoped referring-page export with publisher, target URL and context, validated for relevance.',
        })
    if page_links:
        withheld.append({
            'candidate': 'Incoming internal links to the tracked page', 'status': 'direction_not_observed',
            'source_url': ours_url,
            'reason': 'The captured link inventory records outgoing links from the selected page. It does not establish which other pages link into that URL or the anchor/placement.',
            'next_evidence_needed': 'Identity-matched outgoing-link inventories for the candidate source pages, including rendered anchor and placement where available.',
        })
    return {'schema_version': '1.0', 'keyword': keyword, 'withheld_opportunities': withheld,
            'note': 'These candidates remain internal evidence audit items and are not classified or shown as recommendations.'}


def reconcile_recommendations(deterministic, specialist_result=None, quality_audit=None):
    """Return one authoritative list; only clean, same-target specialist actions can enrich it.

    The deterministic records remain the fail-safe base. Specialist plans with
    any quality finding, missing exact target, or disjoint evidence are kept out
    of the user-facing list and retained in a separate reconciliation audit.
    """
    rows, classification_audit = adapt_recommendations(deterministic or [])
    plans = (specialist_result or {}).get('implementation_plans') or []
    issues = (quality_audit or {}).get('issues') or []
    findings_by_index = {}
    flagged_finding_ids = {}
    for issue in issues:
        path = issue.get('path', '')
        match = re.match(r'implementation_plans\[(\d+)\]', path)
        if match:
            findings_by_index.setdefault(int(match.group(1)), []).append(issue)
        disposition = re.match(r'finding_dispositions\[(\d+)\]', path)
        if disposition:
            index = int(disposition.group(1))
            dispositions = (specialist_result or {}).get('finding_dispositions') or []
            if index < len(dispositions):
                flagged_finding_ids.setdefault(dispositions[index].get('specialist_finding_id'), []).append(issue)
    audit = {'classification_version': 2,
             'excluded_deterministic_recommendations': [item for item in classification_audit['recommendations']
                 if not item.get('eligible')],
             'eligible_specialist_plan_indices': [], 'withheld_specialist_plans': [],
             'enrichments': [], 'authoritative_recommendation_count': len(rows)}
    for index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            audit['withheld_specialist_plans'].append({'index': index, 'reason': 'malformed_plan'})
            continue
        target = plan.get('target_url')
        evidence_ids = set(plan.get('evidence_ids') or [])
        plan_issues = list(findings_by_index.get(index, []))
        for finding_id in plan.get('specialist_finding_ids') or []:
            plan_issues.extend(flagged_finding_ids.get(finding_id, []))
        matches = [row for row in rows if target and _normalized_page(target) == _normalized_page(row.get('target_url'))
                   and evidence_ids.intersection(set((row.get('evidence_provenance') or {}).get('evidence_ids') or []))]
        if plan_issues:
            audit['withheld_specialist_plans'].append({'index': index, 'title': plan.get('title'),
                'reason': 'quality_findings', 'quality_codes': [item.get('code') for item in plan_issues]})
            continue
        if len(matches) != 1:
            audit['withheld_specialist_plans'].append({'index': index, 'title': plan.get('title'),
                'reason': 'missing_or_ambiguous_exact_target_and_evidence_match'})
            continue
        row = matches[0]
        row.setdefault('specialist_provenance', []).append({
            'title': plan.get('title'), 'evidence_ids': sorted(evidence_ids),
            'specialist_finding_ids': list(plan.get('specialist_finding_ids') or []),
            'implementation_steps': list(plan.get('implementation_steps') or []),
        })
        audit['eligible_specialist_plan_indices'].append(index)
        audit['enrichments'].append({'index': index, 'recommendation_id': row.get('id'),
            'target_url': target, 'evidence_ids': sorted(evidence_ids)})
    audit['authoritative_recommendation_count'] = len(rows)
    return rows, audit


def classify_evidence_tier(*, observation_verified, action_supported,
                           established_principle=False, historical_outcome=None,
                           exact_scope_verified=False, action_specific=False,
                           material_uncertainty=False, unsupported_claims=False):
    """Classify evidence and action quality; historical ranking outcomes are irrelevant."""
    if not observation_verified or not action_supported:
        return None
    if unsupported_claims:
        return None
    if established_principle and exact_scope_verified and action_specific and not material_uncertainty:
        return TIER_1
    if established_principle:
        return TIER_2
    return None


def _recommend(code, title, impact, confidence, effort, relevance, evidence,
               rationale, actions, verify, caveat, target_url, action_type="implement",
               *, evidence_tier=TIER_2, tier_basis=None,
               evidence_provenance=None, action_justification=None,
               success_measurement=None, display_action=None, validation_status="validated_rule_evidence",
               recovery_status="not_required"):
    # Simple transparent triage rubric. It is not a predictive SEO score.
    weight = {"high": 3, "medium": 2, "low": 1}
    effort_weight = {"low": 3, "medium": 2, "high": 1}
    # Triage usefulness is deliberately independent of evidence confidence;
    # the evidence tier expresses certainty and the score expresses work value.
    score = 2 * weight[relevance] + weight[impact] + effort_weight[effort]
    priority = "high" if score >= 13 else "medium" if score >= 10 else "low"
    return {
        "id": code, "title": title, "priority": priority,
        "priority_score": score,
        "priority_basis": "Triage rubric: 2*keyword_relevance + potential_impact + inverse_effort; evidence confidence is reported separately and does not affect urgency; ordinal only.",
        "potential_impact": impact,
        "evidence_confidence": confidence,
        "implementation_effort": effort,
        "keyword_relevance": relevance,
        "action_type": action_type,
        "target_url": target_url,
        "impact_estimate": {
            "potential": f"{impact}_qualitative_unquantified",
            "unit": "qualitative_opportunity_not_rank_lift",
            "quantified_rank_or_traffic_lift": None,
            "basis": "Rule-based opportunity assessment, not a validated causal forecast.",
        },
        "evidence": evidence, "interpretation": rationale, "actions": actions,
        "display_action": display_action or " ".join(str(step) for step in actions if step),
        "success_check": verify, "limitations": caveat,
        "evidence_tier": evidence_tier if evidence_tier in {TIER_1, TIER_2} else TIER_2,
        "tier_basis": tier_basis or "Classification is recalculated from verified evidence scope and action quality under schema version 2.",
        "evidence_provenance": evidence_provenance or {"source": "deterministic_analysis_input", "observation": evidence, "target_url": target_url, "benchmark_url": None},
        "action_justification": action_justification or rationale,
        "implementation_details": actions,
        "success_measurement": success_measurement or verify,
        "validation_status": validation_status,
        "recovery_status": recovery_status,
        "status": "proposed_for_review",
    }


def generate_recommendations(*, keyword, ranking_urls, advanced_evidence, onpage,
                             technical_comparison=None, enriched_page_evidence=None):
    """Generate only evidence-supported opportunities; keyword and domains stay dynamic."""
    results = []
    urls = ranking_urls or {}
    ours_url, benchmark_url = urls.get("ours"), urls.get("benchmark")
    if not ours_url or not benchmark_url:
        return []

    backlinks = (advanced_evidence or {}).get("backlinks") or {}
    page = backlinks.get("page") or {}
    page_rank = page.get("rank") or {}
    page_refs = page.get("referring_domains") or {}
    # An aggregate page-level gap does not identify a relevant editorial
    # opportunity. Require an evidence-backed prospect record before suggesting
    # any link acquisition action.
    prospects = page.get("referring_domains_list") or []
    verified_prospects = [row for row in prospects if isinstance(row, dict)
                          and row.get("source_url") and row.get("target_url") == ours_url
                          and row.get("editorial_context_verified") is True
                          and row.get("relevance_verified") is True]
    if verified_prospects and (_num(page_rank.get("ours")) and _num(page_rank.get("competitor"))
            and page_rank["ours"] < page_rank["competitor"]):
        domain_rank = (backlinks.get("domain") or {}).get("rank") or {}
        extra = (f" Domain backlink rank: ours {domain_rank['ours']}, competitor {domain_rank['competitor']}."
                 if _num(domain_rank.get("ours")) and _num(domain_rank.get("competitor")) else "")
        results.append(_recommend(
            "page-link-profile", "Earn relevant editorial references to the ranking page",
            "high", "medium", "high", "high",
            f"Page backlink rank: ours {page_rank['ours']}, competitor {page_rank['competitor']}; "
            f"referring domains: ours {page_refs.get('ours')}, competitor {page_refs.get('competitor')}." + extra,
            "The competitor page has stronger measured link signals, but aggregate counts cannot establish link quality or ranking causation.",
            [f"Review the verified publisher page {verified_prospects[0]['source_url']} and confirm its audience and editorial context still fit {ours_url}.",
             f"If the publisher independently finds {ours_url} useful, provide accurate factual material for an optional editorial citation. Do not pay for a link or prescribe keyword-rich anchor text.",
             "Record the citation only if it is published; later compare the same page-level link metrics and organic query visibility."],
            "Recheck the same page-level link metrics and independent SERP observations over time.",
            "Referring-domain exports are needed to establish link quality; effort is an estimate.",
            ours_url,
            evidence_provenance={"source": "DataForSEO page backlink summary", "observation": f"page rank ours={page_rank['ours']}, benchmark={page_rank['competitor']}; referring domains ours={page_refs.get('ours')}, benchmark={page_refs.get('competitor')}", "target_url": ours_url, "benchmark_url": benchmark_url}))

    intersection = (advanced_evidence or {}).get("keyword_intersection") or {}
    opportunities = intersection.get("top_generic_benchmark_leads") or []
    # Defense in depth: do not trust older/unfiltered advanced evidence.
    domains = (ours_url, benchmark_url)
    safe = []
    for row in opportunities:
        if not isinstance(row, dict):
            continue
        term = row.get("keyword")
        category, _ = classify_opportunity_relevance(term, keyword, domains)
        if category == "relevant_generic" and _num(row.get("our_rank")) and _num(row.get("benchmark_rank")):
            safe.append(row)
    related = intersection.get('related_generic_queries') or []
    mapped_query_gap = any(
        isinstance(row, dict) and _num(row.get('our_rank')) and _num(row.get('benchmark_rank'))
        and row['our_rank'] > row['benchmark_rank']
        and _same_site((row.get('ours_result') or {}).get('url'), ours_url)
        for row in related)
    if intersection.get("status") == "usable" and safe and not mapped_query_gap:
        top = safe[:5]
        terms = ", ".join(f"{r['keyword']} (ours #{r['our_rank']}, benchmark #{r['benchmark_rank']})" for r in top)
        generic_rec = _recommend(
            "generic-query-coverage", "Add useful coverage for a verified related search intent",
            "medium", "medium", "medium", "high",
            f"Shared keyword intersection, filtered generic competitor leads: {terms}.",
            "The competitor leads for these related queries in the saved DataForSEO dataset; these may rank different landing pages.",
            [f"For {ours_url}, confirm the exact landing pages for the listed related searches using a fresh, like-for-like SERP capture; the saved query intersection does not show that this URL ranks for them.",
             "Where a query serves the same audience and intent, add a clearly labeled section that directly answers it using accurate details absent from the current page. Link to that section from the page contents when appropriate, and avoid repeating the phrase unnaturally or creating a near-duplicate page.",
             "If the intent differs, improve a separate suitable page and link it contextually. Re-crawl to confirm the content is visible and indexable, then track the same queries and landing URLs."],
            "Monitor those same query positions and verify content changes against their intent.",
            "Lexical relevance screening is conservative, not semantic intent analysis; third-party or unfamiliar terms require review.",
             ours_url,
             evidence_provenance={"source": "DataForSEO keyword intersection", "observation": f"Relevant generic query leads: {terms}", "target_url": ours_url, "benchmark_url": benchmark_url})
        generic_rec['action_composition'] = {'status': 'specific_copy_withheld_query_landing_pages_unresolved',
            'specificity': 'related search terms are named; exact query-to-URL mapping and current page content are absent',
            'do_not_add_content_until_page_and_intent_are_verified': True}
        results.append(generic_rec)

    # Preserve exact query-to-landing-page identities. These are domain-level
    # search observations; actions improve an existing URL and never create a
    # duplicate page solely because a competitor ranks for a related query.
    query_targets = {}
    demo_targets = {}
    for row in related:
        if not isinstance(row, dict):
            continue
        term = row.get('keyword')
        category, _ = classify_opportunity_relevance(term, keyword, domains)
        ours_result = row.get('ours_result') or {}
        result_url = ours_result.get('url')
        if category != 'relevant_generic' or not result_url or not _same_site(result_url, ours_url):
            continue
        query_tokens = set(re.findall(r'[a-z0-9]+', str(term).casefold()))
        primary_tokens = set(re.findall(r'[a-z0-9]+', str(keyword).casefold()))
        modifiers = query_tokens - primary_tokens
        if modifiers & {'demo', 'practice', 'trial', 'try'}:
            demo_key = _normalized_page(result_url)
            if demo_key and demo_key != _normalized_page(ours_url):
                demo_targets.setdefault(demo_key, row)
            continue
        ours_rank, benchmark_rank = row.get('our_rank'), row.get('benchmark_rank')
        if not (_num(ours_rank) and _num(benchmark_rank) and ours_rank > benchmark_rank):
            continue
        key = _normalized_page(result_url)
        if not key or key == _normalized_page(ours_url):
            continue
        previous = query_targets.get(key)
        if previous is None or (row.get('search_volume') or 0) > (previous.get('search_volume') or 0):
            query_targets[key] = row

    for row in list(query_targets.values())[:2]:
        term = row['keyword']
        result = row.get('ours_result') or {}
        benchmark_result = row.get('benchmark_result') or {}
        target = result['url']
        query_is_instructional = bool(set(re.findall(r'[a-z0-9]+', term.casefold())) &
                                       {'how', 'what', 'guide', 'guides', 'rules', 'learn', 'explained'})
        content_type = ('a clear, accurate step-by-step answer near the beginning, with scannable headings'
                        if query_is_instructional else
                        'a concise section that directly answers the intent expressed by the query')
        result_title = result.get('title') or target
        query_rec = _recommend(
            'existing-query-page-' + _stable_token(target),
            f"Improve the existing page serving '{term}'",
            'medium', 'medium', 'medium', 'high',
            f"The saved domain-level query result for '{term}' maps to {target} (ours #{row['our_rank']}); "
            f"the benchmark maps to {benchmark_result.get('url') or 'a different URL'} "
            f"(#{row['benchmark_rank']}). The tracked result title is '{result_title}'.",
            'The query-to-page mapping identifies an existing asset to improve. It does not show that content is missing or explain the ranking difference.',
            [f"Open the existing page {target} and confirm its current canonical URL, visible content, and whether it already satisfies '{term}'. Do not create a duplicate URL if this page or another first-party resource already answers the same intent.",
             f"If the answer is incomplete, improve this existing page with {content_type}. Keep distinct material that serves another intent, and link contextually to {ours_url} where it helps users continue their journey.",
             f"After approval, verify the updated section is visible and indexable; recheck the same query and exact landing URL for both sites in a comparable saved SERP/Search Console view."],
            'Recheck the same query-to-landing-page pair and organic clicks/impressions when available; no rank change is guaranteed.',
            'Domain-level query rankings can refer to a different page than the primary tracked URL; the mapped URL is an observed search result, not proof that its content is deficient.',
            target,
             evidence_provenance={'source': 'DataForSEO domain keyword intersection with same-domain SERP landing pages',
                                 'evidence_ids': ['KW_QUERY_GAPS'],
                                 'observation': f"{term}: tracked domain #{row['our_rank']} at {target}; benchmark #{row['benchmark_rank']} at {benchmark_result.get('url')}",
                                  'target_url': target, 'benchmark_url': benchmark_result.get('url') or benchmark_url})
        target_context = _page_copy_context(enriched_page_evidence,
            target_url=target, keyword=keyword)
        captured_target = _reliable_page_context(target_context)
        query_rec['action_composition'] = {'status': ('specific_existing_page_with_gap_unverified' if captured_target else
            'existing_query_page_named_but_its_content_was_not_captured'),
            'specific_page_url': target,
            'content_gap_claimed': False,
            'do_not_create_duplicate_content': True,
            'captured_heading_evidence': _heading_texts(target_context, 'h1') +
                _heading_texts(target_context, 'h2') if captured_target else [],
            'limitation': 'The saved query-to-page mapping establishes an existing asset and its observed ranking, not that its content is deficient.'}
        results.append(query_rec)

    # Surface an existing same-domain demo/trial resource when the tracked page
    # does not link to it. This is a navigation opportunity, not a claim that
    # the business lacks the experience or that the competitor's link caused rank.
    page_links = _enriched_rows(enriched_page_evidence, 'outgoing_internal_link_inventory', 'ours')
    linked_destinations = set()
    for link_row in page_links:
        if _normalized_page(link_row.get('page', {}).get('url')) != _normalized_page(ours_url):
            continue
        linked_destinations.update(_normalized_page(item.get('destination_url'))
                                   for item in (link_row.get('value') or []) if isinstance(item, dict))
    for key, row in demo_targets.items():
        if key in linked_destinations:
            continue
        ours_result = row.get('ours_result') or {}
        target = ours_result.get('url')
        if not target:
            continue
        title = ours_result.get('title') or target
        trial_rec = _recommend(
            'existing-trial-resource-' + _stable_token(target),
            'Make an existing related experience easier to find',
            'medium', 'medium', 'low', 'high',
            f"For the related query '{row['keyword']}', the saved domain result maps to the existing first-party page {target} (ours #{row['our_rank']}, benchmark #{row['benchmark_rank']}). The tracked page's captured outgoing-link inventory does not include that URL.",
            'A contextual route can help visitors with this pre-use intent reach an existing resource. The saved query result does not establish that the resource is suitable for every visitor or that navigation affects rankings.',
            [f"Confirm that {target} is current, available, and accurately described by its captured title ('{title}').",
             f"If suitable for this page and its policies, add one visible contextual link from {ours_url} near the relevant explanation or next-step CTA, using a natural label that describes the destination. Do not create another page or imply functionality the destination does not provide.",
             'Test the rendered link and destination on mobile and desktop, confirm the page remains indexable, and measure clicks to the resource plus the same query-to-URL result over time.'],
            'May improve discovery of an existing resource for visitors expressing the related intent; no ranking benefit is established.',
            'Saved domain-level ranking and one page crawl do not prove the resource is globally undiscoverable or that this page is the only suitable entry point.',
             ours_url,
            evidence_provenance={'source': 'DataForSEO domain keyword intersection and exact-page outgoing-link inventory',
                                 'evidence_ids': ['KW_QUERY_GAPS'] + [x.get('evidence_id') for x in page_links if x.get('evidence_id')],
                                 'observation': f"{row['keyword']} maps to existing {target}; captured outgoing links from {ours_url} do not include it.",
                                  'target_url': ours_url, 'benchmark_url': benchmark_url})
        trial_rec['proposed_link_pairs'] = [{'source_url': ours_url, 'destination_url': target,
            'direction': 'tracked_page_to_existing_related_resource',
            'status': 'destination_absent_from_saved_outgoing_link_capture; suitability_requires_review'}]
        trial_rec['action_composition'] = {'status': 'specific_existing_page_pair',
            'placement': 'near the relevant explanation or next-step call to action, after page and policy review',
            'anchor_guidance': 'natural wording describing the destination; do not imply unverified functionality'}
        results.append(trial_rec)
        break

    # Existing related resources allow a conditional return-link proposal,
    # without treating links counted on the target page as incoming links.
    heading_rows = []
    for row in _enriched_rows(enriched_page_evidence, 'rendered_heading_inventory', 'ours'):
        if _normalized_page(row.get('page', {}).get('url')) == _normalized_page(ours_url):
            heading_rows = row.get('value') or []
            break
    link_inventory = []
    for row in page_links:
        if _normalized_page(row.get('page', {}).get('url')) == _normalized_page(ours_url):
            link_inventory = row.get('value') or []
            break
    supporting = []
    preserved_sections = []
    for item in link_inventory:
        source_url = item.get('destination_url') if isinstance(item, dict) else None
        matched_headings = (_resource_topic_matches(source_url, heading_rows, keyword)
                            if source_url and _same_site(source_url, ours_url) else [])
        if (not source_url or not _same_site(source_url, ours_url) or
                _normalized_page(source_url) == _normalized_page(ours_url) or not matched_headings):
            continue
        if source_url not in supporting:
            supporting.append(source_url)
        preserved_sections.extend(label for label in matched_headings if label not in preserved_sections)
    if len(supporting) >= 2:
        sources = supporting[:6]
        destinations = ', '.join(sources)
        evidence_ids = [row.get('evidence_id') for row in page_links if row.get('evidence_id')]
        preserve_action = (("Retain these existing, captured content sections where they remain accurate and useful: " +
                           ', '.join(preserved_sections[:8]) + '. Do not expand the primary page merely to imitate a competitor.')
                          if preserved_sections else
                          'Keep useful existing sections and destinations accurate; do not add copy solely to imitate a competitor.')
        pair_text = '; '.join(f'{source} to {ours_url}' for source in sources)
        cluster_rec = _recommend(
            'internal-resource-cluster', 'Connect existing related resources to the tracked page',
            'medium', 'medium', 'medium', 'high',
            f"The exact-page crawl shows {ours_url} links out to these related first-party resources: {destinations}. The saved crawl does not include their outgoing links back to the tracked page.",
            'A clear two-way contextual path can help users move between the main page and useful supporting material. Link counts do not prove a ranking effect or establish that a return link is missing.',
             [f"The saved crawl confirms outgoing links from {ours_url} to these existing pages: {destinations}. It does not establish that any of those pages link back.",
              f"Check these proposed source-to-destination pairs: {pair_text}. For each source page, confirm a relevant section and verify the current rendered links. Only when the contextual link to {ours_url} is absent, add one in-body link with wording that describes the tracked destination. Source-page content and reverse-link status were not captured; verify them before editing and do not add links to match a count.",
             preserve_action,
             'Verify the rendered source-page link and exact destination URL, and check that the main page and supporting content remain crawlable.'],
            'Can improve navigation and discovery of the existing content cluster; no ranking change is established.',
            'The crawl records outgoing destination URLs only, not anchor text, placement, or incoming links. Check current source pages before editing.',
            ours_url,
             evidence_provenance={'source': 'identity-matched Playwright page crawl',
                                 'evidence_ids': evidence_ids,
                                 'observation': f"Captured outgoing links from {ours_url} to {destinations}; reverse-link status is not captured.",
                                  'target_url': ours_url, 'benchmark_url': benchmark_url})
        cluster_rec['proposed_link_pairs'] = [{'source_url': source, 'destination_url': ours_url,
            'direction': 'supporting_page_to_tracked_page',
            'status': 'proposed_pair_to_check; return_link_absence_not_observed'} for source in sources]
        cluster_rec['action_composition'] = {'status': 'specific_source_destination_pairs_but_source_pages_unverified',
            'placement': 'relevant existing in-body context only, after source page and current link inventory review',
            'incoming_link_claim': False}
        results.append(cluster_rec)

    metadata = (
        (
            "title_keyword_match", "HTML title", "medium", "high",
            "HTML title can help communicate page topic to search engines.",
            "Google may rewrite the displayed search-result title; exact keyword presence alone is not a ranking-quality metric.",
        ),
        (
            "meta_keyword_match", "meta description", "low", "medium",
            "Meta descriptions can affect search-result snippets and clicks; keyword presence is not a direct ranking boost.",
            "Google may generate its own search-result snippet instead of using the meta description. Editing it does not guarantee higher rankings or clicks.",
        ),
        (
            "h1_keyword_match", "main H1", "medium", "high",
            "A descriptive H1 helps users understand the page topic.",
            "An exact-match keyword in an H1 is not required; the heading should accurately describe the visible page content.",
        ),
    )
    ours_copy_context = _page_copy_context(enriched_page_evidence,
        target_url=ours_url, keyword=keyword)
    benchmark_metadata_rows = _identity_enriched_rows(enriched_page_evidence,
        'page_metadata_and_rendering', side='benchmark', target_url=benchmark_url,
        keyword=keyword)
    benchmark_metadata = (benchmark_metadata_rows[0].get('value') or {}
                          if benchmark_metadata_rows else {})
    for field, label, impact, relevance, role, caveat in metadata:
        row = (onpage or {}).get(field) or {}
        if row.get("ours") is False and row.get("competitor") is True:
            current_value = (ours_copy_context.get('metadata') or {}).get(
                {'title_keyword_match': 'title', 'meta_keyword_match': 'meta_description',
                 'h1_keyword_match': 'title'}.get(field, 'title'))
            competitor_value = benchmark_metadata.get(
                {'title_keyword_match': 'title', 'meta_keyword_match': 'meta_description',
                 'h1_keyword_match': 'title'}.get(field, 'title'))
            proposal = None
            if field == 'title_keyword_match':
                proposal = _compose_title_candidate(keyword, ours_url, ours_copy_context,
                                                   competitor_value or '')
            elif field == 'meta_keyword_match':
                proposal = _compose_meta_candidate(keyword, ours_url, ours_copy_context)
            evidence = f"Keyword '{keyword}' was not detected in our captured {label}, but was detected in the competitor's."
            if current_value and competitor_value:
                evidence = (f"Captured tracked-page {label}: ‘{current_value}’. Captured benchmark {label}: "
                            f"‘{competitor_value}’. The selected keyword '{keyword}' was not detected in the tracked value but was detected in the benchmark value.")
            if proposal:
                field_name = 'HTML title' if proposal['field'] == 'title' else 'meta description'
                basis = '; '.join(proposal['basis'])
                observed_text = proposal['replaces_observed']
                candidate_text = proposal['candidate']
                if proposal['field'] == 'title':
                    action = (f'On {ours_url}, replace the captured {field_name} "{observed_text}" with this proposed candidate (not observed source text): "{candidate_text}". '
                              f"It is grounded in the tracked page's captured heading evidence ({basis}); do not copy the benchmark title. "
                              "Confirm the exact URL is canonical and indexable, preview for truncation and duplication, then re-crawl and verify the proposed title appears in the rendered HTML."
                              )
                else:
                    action = (f'On {ours_url}, replace the captured meta description "{observed_text}" with this proposed candidate (not observed source text): "{candidate_text}". '
                              f"It summarizes captured page headings and visible text ({basis}); it is for search-result presentation, not a direct ranking boost. "
                              "Check factual accuracy and policy wording, preview for truncation, then re-crawl and confirm the description in rendered HTML. Google may choose a different snippet.")
                actions = [action]
                action_status = 'candidate_proposed_from_identity_matched_page_evidence'
                display_action = action
            else:
                action = (f"Do not draft or publish replacement {label} text from the keyword mismatch alone. The saved evidence does not contain enough identity-matched page headings and visible content to ground an example. "
                          f"Capture the rendered {label}, main heading and relevant visible sections for {ours_url}; then prepare a candidate only from text supported by that page. Verify canonical/indexable status and preview the rendered result before deployment.")
                actions = [action]
                action_status = 'specific_copy_withheld_insufficient_page_evidence'
                display_action = action
            rec = _recommend(
                "onpage-" + field, f"Verify {label} targeting for the selected keyword",
                impact, "medium", "low", relevance,
                evidence,
                f"This is a captured-page difference, not a verified defect. {role}",
                actions,
                "Recrawl the exact URL after approval and compare search appearance over time.",
                caveat,
                ours_url, action_type="verify_before_edit",
                evidence_provenance={"source": "captured on-page comparison", "observation": f"{label} keyword detection ours=false, benchmark=true", "target_url": ours_url, "benchmark_url": benchmark_url,
                    'evidence_ids': ours_copy_context.get('evidence_ids', []) + [r.get('evidence_id') for r in benchmark_metadata_rows]},
                display_action=display_action)
            rec['action_composition'] = {'status': action_status,
                'specific_copy_generated': bool(proposal),
                'negative_reason': None if proposal else 'Identity-matched captured page copy/headings were insufficient.',
                'proposed_copy': proposal}
            results.append(rec)

    # Detailed investigations are accepted only after the analysis pipeline has
    # validated both exact SERP URLs and the mobile Lighthouse audits.
    detailed = ((technical_comparison or {}).get("mobile") or {}).get("detailed_analysis") or {}
    verified_investigations = (
        [row for row in detailed.get("investigations", []) if isinstance(row, dict)
         and row.get("confidence") == "investigation_only" and row.get("title")
         and row.get("supporting_observation") and row.get("actions")]
        if detailed.get("status") == "usable" and detailed.get("scope") == "exact_serp_pages_mobile_lab"
        else []
    )
    technical = (advanced_evidence or {}).get("technical") or {}
    for device, data in technical.items():
        metrics = data.get("lab_metrics") or {}
        lcp = (metrics.get("largest_contentful_paint_ms") or {}).get("ours")
        tbt = (metrics.get("total_blocking_time_ms") or {}).get("ours")
        cls = (metrics.get("cumulative_layout_shift") or {}).get("ours")
        issues = []
        if _num(lcp) and lcp > 4000:
            issues.append(f"LCP {lcp / 1000:.2f}s")
        if _num(tbt) and tbt > 600:
            issues.append(f"TBT {tbt:.0f}ms")
        if _num(cls) and cls > 0.25:
            issues.append(f"CLS {cls:.3f}")
        if issues:
            has_detail = device == "mobile" and bool(verified_investigations)
            if has_detail:
                labels = (("javascript_execution", "JavaScript execution"),
                          ("unused_javascript", "unused JavaScript"),
                          ("image_delivery", "image delivery"),
                          ("render_blocking", "render-blocking resources"))
                labels_by_area = dict(labels)
                resources_by_area = {}
                observations_by_area = {}
                for finding in verified_investigations:
                    area = finding.get('area')
                    resources_by_area.setdefault(area, [])
                    observations_by_area.setdefault(area, [])
                    if finding.get('supporting_observation'):
                        observations_by_area[area].append(str(finding['supporting_observation']))
                    for resource in finding.get('affected_resources') or []:
                        if not isinstance(resource, dict) or not resource.get('url'):
                            continue
                        resources_by_area[area].append(resource)
                measure_by_area = {'javascript_execution': 'total', 'unused_javascript': 'wastedBytes',
                                   'image_delivery': 'wastedBytes', 'render_blocking': 'wastedMs',
                                   'lcp_breakdown': 'total'}
                area_order = ('javascript_execution', 'unused_javascript', 'image_delivery',
                              'render_blocking', 'lcp_breakdown')
                for area in area_order:
                    if area not in labels_by_area:
                        continue
                    measure_key = measure_by_area[area]
                    resources = sorted(resources_by_area.get(area, []),
                                       key=lambda row: row.get(measure_key) if _num(row.get(measure_key)) else -1,
                                       reverse=True)
                    selected_resources = []
                    seen_resources = set()
                    for resource in resources[:(2 if area in {'javascript_execution', 'unused_javascript'} else 1)]:
                        if resource['url'] in seen_resources:
                            continue
                        seen_resources.add(resource['url'])
                        selected_resources.append(resource)
                    composed = _compose_technical_action({area}, selected_resources, ours_url)
                    if not composed:
                        continue
                    action, resource_details = composed
                    observation = '; '.join(observations_by_area.get(area, []))
                    resource_label = labels_by_area[area]
                    resource_names = ', '.join(row['name'] for row in resource_details)
                    display_action = (f"On the tracked page, review {resource_names} for the {resource_label} issue. "
                        + ('For same-site code, change only work confirmed non-critical; third-party code needs owner/vendor approval before any loading change. ' if area in {'javascript_execution', 'unused_javascript'} else
                           'Confirm the owning team and dependency before changing this resource. ')
                        + 'Preserve security and essential functionality, then repeat the same mobile Lighthouse run and primary journey.')
                    rec = _recommend(
                        f"technical-{device}-{area}", f"Improve {resource_label} on the tracked page",
                        "medium", "high", "medium", "high",
                        f"The saved {device} Lighthouse run flagged {resource_label} on the tracked page; exact affected resources and measurements are retained in the technical appendix.",
                        f"Optimising this specific resource may reduce avoidable work in the {resource_label.lower()} path and improve loading experience. The lab observation does not establish ranking causation.",
                        [action],
                        "Repeat the same mobile Lighthouse audit, compare the relevant resource measurement, and verify the primary page journey.",
                        f"Diagnostic is an investigation target; validate the current resource, ownership and functionality before changing it. {resource_label} changes can affect page behavior.",
                        ours_url,
                        evidence_provenance={"source": "Lighthouse exact-page lab audit and detailed diagnostics",
                            "observation": f"{resource_label}: {observation or resource_notes[0]}; " + ", ".join(issues),
                            "target_url": ours_url, "benchmark_url": benchmark_url,
                             "resource_candidates": selected_resources,
                             "diagnostic_areas": [area]},
                        display_action=display_action)
                    rec['action_composition'] = {'status': 'specific_resource_action_composed',
                        'resource_names': [row['name'] for row in resource_details],
                        'resource_ownership': [{'name': row['name'], 'host_class': row['ownership']}
                                               for row in resource_details],
                        'third_party_resources_require_owner_review': any(
                            row['ownership'] == 'third-party-host' for row in resource_details)}
                    results.append(rec)
            else:
                # Summary metrics do not locate a fix. Retain them in the audit
                # until resource-level evidence can support a concrete action.
                continue

    results = _merge_overlapping_javascript_actions(results, ours_url)
    # Adapt and re-evaluate every generated row under the current evidence
    # contract before the existing priority score orders peers.
    results, _classification_audit = adapt_recommendations(results)
    # Tier confidence controls ordering before operational triage.
    effort_rank = {"low": 0, "medium": 1, "high": 2}
    tier_rank = {TIER_1: 1, TIER_2: 2}
    results.sort(key=lambda r: (tier_rank[r["evidence_tier"]], -r["priority_score"], effort_rank[r["implementation_effort"]], r["id"]))
    for index, row in enumerate(results, 1):
        row["order"] = index
        row["tie_break_explanation"] = None

    # Explain every equal-score group, including the last item in the group.
    from itertools import groupby
    for (tier, score), grouped in groupby(results, key=lambda r: (r["evidence_tier"], r["priority_score"])):
        peers = list(grouped)
        if len(peers) < 2:
            continue
        for position, row in enumerate(peers):
            if position == 0:
                next_row = peers[1]
                if effort_rank[row["implementation_effort"]] < effort_rank[next_row["implementation_effort"]]:
                    reason = (f"Placed before '{next_row['title']}' because estimated effort is "
                              f"{row['implementation_effort']} versus {next_row['implementation_effort']}.")
                else:
                    reason = "Equal effort; stable recommendation ID determines order."
            else:
                prev_row = peers[position - 1]
                if effort_rank[row["implementation_effort"]] > effort_rank[prev_row["implementation_effort"]]:
                    reason = (f"Placed after '{prev_row['title']}' because estimated effort is "
                              f"{row['implementation_effort']} versus {prev_row['implementation_effort']}.")
                else:
                    reason = "Equal effort; stable recommendation ID determines order."
            row["tie_break_explanation"] = (f"Equal triage score ({score}) within {tier}; {reason} "
                                             "This is a workflow tie-break, not a ranking-impact prediction.")
    return results


def format_recommendations_report(keyword, urls, findings, recommendations, quality):
    lines = ["=== SEO PHASE 2 RECOMMENDATION REPORT ===", f"Keyword: {keyword}",
             f"Our ranking URL: {urls.get('ours')}", f"Benchmark ranking URL: {urls.get('benchmark')}",
             f"Findings: {len(findings)}", f"Recommendations: {len(recommendations)}", ""]
    lines += ["=== EVIDENCE QUALITY ==="]
    lines += [f"{k}: {v}" for k, v in quality.items()]
    lines += ["", "=== PRIORITIZED RECOMMENDATIONS ==="]
    if not recommendations:
        lines.append("No supported recommendations generated from currently verified evidence.")
    for item in recommendations:
        lines += [
            f"{item['order']}. {item['title']}",
            f"   Priority: {item['priority']} (triage score {item['priority_score']}; not a ranking forecast)",
            f"   Potential impact: {item['potential_impact']} (not a rank-lift forecast)",
            f"   Evidence confidence: {item['evidence_confidence']}",
            f"   Evidence tier: {item['evidence_tier']}",
            f"   Implementation effort: {item['implementation_effort']}",
            f"   Keyword relevance: {item['keyword_relevance']}",
            f"   Action type: {item['action_type']}",
            f"   Target URL: {item['target_url']}",
            f"   Evidence: {item['evidence']}",
            f"   Interpretation: {item['interpretation']}",
        ]
        if item.get("tie_break_explanation"):
            lines.append(f"   Priority tie-break: {item['tie_break_explanation']}")
        lines += [f"   Action: {action}" for action in item["actions"]]
        lines += [f"   Validate: {item['success_check']}", f"   Caveat: {item['limitations']}", ""]
    lines += ["Important: Differences are observational, not proof of search-ranking causation or guaranteed uplift."]
    return "\n".join(lines) + "\n"
