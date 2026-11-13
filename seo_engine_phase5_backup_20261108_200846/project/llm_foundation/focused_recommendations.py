"""Evidence-scoped recommendation development; deterministic, lossless assembly.

This is a second layer after the four existing Gemma specialists. Each task is
independently requested and validated; no fifth summarizing LLM request occurs.
"""
from __future__ import annotations

import copy
import hashlib
import json

from .action_coverage import validate_action_coverage
from .executive_synthesis import TASKS, parse_response, validate_executive
from .structured_facts import publish_verified_response
from analysis.recommendation_classification import (
    CLASSIFICATION_VERSION, TIER_2, TIER_ORDER, classify_recommendation,
)

PROMPT_VERSION = 'focused-actions-v4-evidence-to-action'
RECOMMENDATION_ENGINE = 'four_specialist_focused_v4'
# Fixed evidence categories, not keyword, company, or URL rules.
TASK_FACTS = {
    'onpage': ('ON_TITLE', 'ON_LINKS', 'ON_CONTENT_SIMILARITY'),
    'backlinks': ('BL_PAGE', 'BL_DOMAIN', 'SERP'),
    'technical': ('TECH_LAB', 'TECH_INV'),
    'competition': ('SERP', 'KW_SHARED', 'KW_QUERY_GAPS'),
}


def task_packet(packet, task):
    if task not in TASKS:
        raise ValueError('Unknown specialist task: ' + str(task))
    findings = [copy.deepcopy(row) for row in packet['specialist_findings'] if row['task'] == task]
    fact_ids = set(TASK_FACTS[task])
    fact_ids.update(packet.get('enriched_fact_ids', {}).get(task, []))
    facts = [copy.deepcopy(row) for row in packet['facts'] if row['id'] in fact_ids]
    scoped = {key: copy.deepcopy(packet[key]) for key in ('schema_version', 'keyword', 'market', 'search_engine', 'tracked', 'benchmark', 'limitations') if key in packet}
    scoped.update(facts=facts, specialist_findings=findings,
                  enriched_evidence_ids=list(packet.get('enriched_fact_ids', {}).get(task, [])),
                  specialist_fact_links={row['id']: [ref for ref in packet['specialist_fact_links'].get(row['id'], []) if ref in fact_ids] for row in findings},
                  require_action_coverage=True)
    return scoped


def task_request(scoped, task):
    instruction = (
        'You are translating saved SEO evidence into one preferred, implementable recommendation when evidence supports a change. '
        'Use MATCH (close a verified meaningful gap), IMPROVE (fix a verified weakness), OUTPERFORM (add verified user value), '
        'DEFEND (preserve a demonstrated strength), or DO_NOT_PURSUE (avoid an unsupported change) as internal reasoning labels; '
        'do not present a menu of generic options. '
        'Return ONLY valid JSON with exactly schema_version="1.0", task, implementation_plans, finding_dispositions. '
        'Use the current investigation keyword, exact URLs and facts, never generic site names. '
        'For EVERY specialist finding return exactly one finding_dispositions entry: '
        '{specialist_finding_id, outcome (action|merged|investigate|deferred), plan_indices (zero-based within THIS response), '
        'simple_explanation, technical_explanation, next_step, reason, evidence_ids}. '
        'Every actionable or merged finding MUST link to a plan citing that finding; unsupported findings MUST be investigated or deferred with a concrete reason. '
        'For each finding, inspect specialist_fact_links[ID] BEFORE selecting an outcome. '
        'If its mapping is empty, set outcome=investigate or deferred, plan_indices=[], evidence_ids=[], '
        'and give a specific next_step explaining what source data must be collected or verified; '
        'NEVER include that finding in any implementation_plan.specialist_finding_ids. '
        'If outcome=action or merged, provide nonempty plan_indices and cite the finding in each linked plan. '
        'Every plan is a preferred action with a concrete change to the exact tracked page or a specific off-page/technical workflow; '
        'do not make the plan itself only an audit, investigation, analysis or review. Put verification after the implementation, '
        'not in place of it. If no safe concrete change is supported, keep the finding investigate/deferred with no plan. '
        'Every plan must be referenced by at least one actionable or merged finding. '
        'A finding with outcome=investigate or deferred MUST NOT link to a plan, even if another finding shares the topic. '
        'For each plan return {title,rationale,owner,priority (high|medium|low|investigate), '
        'implementation_steps (specific instructions),success_measure,uncertainty,evidence_ids,specialist_finding_ids, '
        'simple_explanation,technical_explanation}. '
        'Explain the verified evidence and why this specific change is sensible. Explain the business implication simply, '
        'then give detailed technical instructions naming the affected page/element/workflow, execution steps, dependencies and verification. '
        'Success measures must be measurable and scoped to the action (rendered page fields, relevant link destinations, '
        'controlled lab measurements, field data where available, or the same saved queries over time); distinguish implementation checks '
        'from ranking outcomes and never set arbitrary numeric targets. Prioritize by evidence strength, likely user/search benefit and effort; '
        'priority is workflow triage, not a ranking forecast. '
        'Cite only FACT IDs supplied here and only factual links allowed for each specialist ID. '
        'ENR facts are bounded saved observations with source, page identity, scope, limitations and provenance. '
        'Use qualitative passages, headings, link destinations and technical details only when relevant; cite their ENR evidence IDs. '
        'A missing anchor, incoming link, topic, or observation means it was not captured or not present in this packet; do not infer it. '
        'For each plan, its evidence_ids must be approved FACT IDs linked to its specialist_finding_ids; '
        'for each disposition, evidence_ids must be a subset of that specialist finding approved links. '
        'When discussing a lexical content similarity metric, do not infer content quality or search relevance from it alone. '
        'Never treat a specialist interpretation as a proven ranking cause, claim measured benefits without evidence, '
        'or describe internal link counts as density. If evidence is insufficient, explain what must be checked. '
        'Avoid making up measurements or promising ranking improvements. '
        'Numbers in approved FACT values describe observations, not mandatory implementation targets. '
        'Do not invent specific quantities, numeric ranges, percentages, deadlines, or success thresholds for recommended changes. '
        'If the evidence does not justify an exact target, use conditional steps: audit first, select changes based on verified needs, and verify the outcome. '
        'Keep actual observed numbers only with correct evidence citations, and do not confuse outgoing page links with incoming links. '
        'For content, improve the selected existing page when it fits its purpose; propose a separate page only after exact query URLs, intent, '
        'and existing-page coverage support that choice. Do not prescribe word counts or backlink-volume targets. '
        'For internal links, use captured outgoing destinations only as source pages to consider; do not claim they are incoming links. '
        'For performance, make a specific remedy conditional on profiling a cited diagnostic, and preserve security, fraud prevention, consent and core flows. '
        'Preserve demonstrated strengths and avoid changes likely to damage them. Prefer merging related findings into one preferred plan rather than redundant plans. '
        'No more than five plans in this specialist task. Do not repeat the full specialist findings in the response.'
    )
    if task == 'backlinks':
        instruction += (
            ' BACKLINK EVIDENCE SCOPE: Use specialist_fact_links as the authoritative mapping. '
            'BL_PAGE measures backlinks and referring domains to the exact selected pages; '
            'BL_DOMAIN measures domain-wide link counts and scores; SERP measures only observed rankings. '
            'Never use BL_DOMAIN alone to claim a specific page has fewer links, or BL_PAGE alone to claim a ranking position. '
            'If a plan requires both page and domain facts, cite BOTH relevant specialist findings in '
            'specialist_finding_ids and ensure the corresponding finding_dispositions reference that plan. '
            'Do not attach BL_PAGE to a plan citing only a domain-level specialist finding unless that '
            'specialist_fact_links mapping explicitly allows BL_PAGE. '
            'Avoid treating link volume as link quality, domain authority, link equity, or a proven cause of a ranking gap. '
            'Do not invent targets for new links, referring domains, domain-authority thresholds, '
            'percent growth, outreach counts, or delivery dates. '
            'Set success_measure to verifiable actions and evidence collection without arbitrary numerical quotas. '
            'When referring-domain lists, quality indicators, or link provenance are unavailable, '
            'recommend collecting and reviewing them before outreach. '
            'Keep all plans and dispositions strictly grounded in the cited specialist evidence.'
        )
    if task == 'onpage':
        instruction += (
            ' Use exact saved headings, content passages, metadata, structured-data summaries and outgoing destinations when relevant. '
            'Recommend concrete existing-page edits such as a more accurate topic-specific title, filling an evidenced user-intent gap '
            'on the current page, or a contextual link from an evidenced relevant source. Do not infer FAQ or topical gaps from an incomplete capture.'
        )
    if task == 'technical':
        instruction += (
            ' For Lighthouse diagnostics, cite the exact observation and resource/audit if supplied. Do not claim a diagnostic causes LCP or rankings. '
            'Give an implementation direction conditional on profiling, with security and business-function safeguards.'
        )
    if task == 'backlinks':
        instruction += (
            ' A page-level opportunity must be page-specific. Domain-level totals and scores are separate context and cannot establish a page gap. '
            'Without referring-domain identities, do not invent target websites or claim link quality; only propose a specific legitimate link-earning '
            'improvement when the page/resource evidence supports it, otherwise preserve the unresolved finding.'
        )
    if task == 'competition':
        instruction += (
            ' Competition facts: KW_SHARED provides aggregate lead COUNTS, not individual keyword positions. '
            'KW_QUERY_GAPS, if present, contains verified historical per-query DOMAIN ranks and gaps. '
            'Cite KW_QUERY_GAPS for specific related-query rankings and gap numbers; never infer exact ranking-page URLs. '
            'Do not cite KW_SHARED for individual ranks or rank gaps. '
            'Only state numbers present in the supplied approved facts. '
            'Findings with empty specialist_fact_links require investigate/deferred, no plan_indices and no plan citation. '
            'A discovery candidate is not a verified ranking competitor. Prefer improving the existing tracked page for relevant query intent; '
            'do not propose duplicate pages based on domain ranks until exact ranking URLs, intent and existing coverage justify them.'
        )
    body = json.dumps({'task': task, 'investigation': scoped}, ensure_ascii=False, separators=(',', ':'))
    return instruction, body


def fingerprint(scoped, task, model):
    system, prompt = task_request(scoped, task)
    content = json.dumps({'version': PROMPT_VERSION, 'model': model, 'system': system, 'prompt': prompt}, sort_keys=True)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _as_executive(task_result, scoped):
    # Reuse the existing strict numeric, citation, factual and coverage validators.
    return {'schema_version': '1.0', 'status': 'usable',
            'executive_summary': 'Review the saved evidence and verify the recommended changes before implementation.',
            'executive_summary_evidence_ids': [scoped['facts'][0]['id']] if scoped['facts'] else [],
            'key_findings': [], 'proposed_decisions': [], 'limitations': list(scoped.get('limitations', [])),
            'implementation_plans': copy.deepcopy(task_result['implementation_plans']),
            'finding_dispositions': copy.deepcopy(task_result['finding_dispositions'])}


def validate_task(result, scoped, task):
    errors = []
    if not isinstance(result, dict):
        return ['Task output must be an object']
    if set(result) != {'schema_version', 'task', 'implementation_plans', 'finding_dispositions'}:
        errors.append('Task output must contain only schema_version, task, implementation_plans and finding_dispositions')
    if result.get('schema_version') != '1.0' or result.get('task') != task:
        errors.append('Task identity or schema version mismatch')
    plans, rows = result.get('implementation_plans'), result.get('finding_dispositions')
    if not isinstance(plans, list) or not isinstance(rows, list):
        return errors + ['implementation_plans and finding_dispositions must be arrays']
    if len(plans) > 5:
        errors.append('More than five plans in a single specialist task')
    if not scoped['facts'] and plans:
        errors.append('Cannot create factual implementation plans without approved task evidence')
    task_ids = {f['id'] for f in scoped['specialist_findings']}
    allowed_facts = {f['id'] for f in scoped['facts']}
    for i, plan in enumerate(plans):
        if not isinstance(plan, dict):
            continue
        if not set(plan.get('specialist_finding_ids') or []).issubset(task_ids):
            errors.append(f'implementation_plans[{i}]: cross-specialist finding reference')
        if not set(plan.get('evidence_ids') or []).issubset(allowed_facts):
            errors.append(f'implementation_plans[{i}]: out-of-scope factual reference')
        linked_facts = {ref for fid in plan.get('specialist_finding_ids') or []
                        for ref in scoped['specialist_fact_links'].get(fid, [])}
        if not set(plan.get('evidence_ids') or []).issubset(linked_facts):
            errors.append(f'implementation_plans[{i}]: fact not linked to cited specialist findings')
        if not any(i in (row.get('plan_indices') or []) for row in rows if isinstance(row, dict)):
            errors.append(f'implementation_plans[{i}]: orphan plan without linked finding')
    # Validate the original task response, without accepting synthetic executive claims.
    if scoped['facts']:
        errors.extend(validate_executive(_as_executive(result, scoped), scoped))
    else:
        errors.extend(validate_action_coverage(_as_executive(result, scoped), scoped))
    return list(dict.fromkeys(errors))


def merge_tasks(packet, outputs):
    if set(outputs) != set(TASKS):
        raise ValueError('All four validated specialist outputs are required before merging')
    plans, dispositions = [], []
    for task in TASKS:
        scoped = task_packet(packet, task)
        result = outputs[task]
        errors = validate_task(result, scoped, task)
        if errors:
            raise ValueError(f'{task} did not validate: ' + '; '.join(errors[:5]))
        offset = len(plans)
        plans.extend(copy.deepcopy(result['implementation_plans']))
        for row in result['finding_dispositions']:
            item = copy.deepcopy(row)
            item['plan_indices'] = [index + offset for index in item['plan_indices']]
            dispositions.append(item)
    tracked, benchmark = packet['tracked'], packet['benchmark']
    summary = (f"For the saved search for '{packet.get('keyword')}', {tracked['domain']} was observed "
               f"at position {tracked['position']} and {benchmark['domain']} at position {benchmark['position']}. "
               'This is one historical search observation, not proof of ranking causation. '
               'The detailed evidence-backed action plans follow.')
    priority = {'high': 0, 'medium': 1, 'investigate': 2, 'low': 3}
    # Classification is provisional here; published rows are re-evaluated
    # against verified scope, action specificity and uncertainty below.
    for plan in plans:
        plan['legacy_evidence_tier'] = plan.get('legacy_evidence_tier', plan.get('evidence_tier'))
        plan['evidence_tier'] = TIER_2
        plan['tier_basis'] = 'Re-evaluated after citation, page-scope, action-specificity and uncertainty checks.'
        plan['evidence_provenance'] = {
            'source': 'validated canonical evidence packet',
            'evidence_ids': list(plan.get('evidence_ids') or []),
            'specialist_finding_ids': list(plan.get('specialist_finding_ids') or []),
            'tracked_url': tracked.get('url'), 'benchmark_url': benchmark.get('url'),
        }
        plan['action_justification'] = plan.get('rationale')
        plan['implementation_details'] = list(plan.get('implementation_steps') or [])
        plan['success_measurement'] = plan.get('success_measure')
        plan['validation_status'] = 'validated_citations_numeric_scope_and_lineage'
        plan['recovery_status'] = 'not_required'
    plan_metadata = []
    metadata_fields = ('evidence_tier', 'legacy_evidence_tier', 'tier_basis', 'evidence_provenance', 'action_justification',
                       'implementation_details', 'success_measurement', 'validation_status', 'recovery_status')
    for plan in plans:
        plan_metadata.append({key: plan.pop(key) for key in metadata_fields})
    decisions = []
    indexed_plans = sorted(enumerate(plans), key=lambda row: priority.get(row[1].get('priority'), 4))
    for index, plan in indexed_plans[:3]:
        decisions.append({'title': plan['title'], 'owner': plan['owner'],
                          'action': plan['implementation_steps'][0], 'success_check': plan['success_measure'],
                          'evidence_ids': plan['evidence_ids'], 'limitation': plan['uncertainty']})
    merged = {'schema_version': '1.0', 'status': 'usable', 'executive_summary': summary,
              'executive_summary_evidence_ids': ['SERP'], 'key_findings': [],
              'proposed_decisions': decisions, 'limitations': list(packet.get('limitations', [])),
              'implementation_plans': plans, 'finding_dispositions': dispositions}
    packet = copy.deepcopy(packet)
    packet['require_action_coverage'] = True
    errors = validate_executive(merged, packet)
    if errors:
        raise ValueError('Merged executive failed validation: ' + '; '.join(errors[:8]))
    published, _ = publish_verified_response(merged, packet)
    published_plans = published.get('implementation_plans') or []
    for plan, metadata in zip(published_plans, plan_metadata):
        plan.update(metadata)
    classification_audit = []
    eligible_plan_ids = set()
    for index, plan in enumerate(published_plans):
        classified, audit = classify_recommendation(plan)
        audit['plan_index'] = index
        classification_audit.append(audit)
        if classified is None:
            plan.pop('evidence_tier', None)
            plan.pop('tier_basis', None)
            plan['classification_status'] = 'excluded_from_user_facing_recommendations'
            continue
        plan.update(classified)
        eligible_plan_ids.add((plan.get('title'), tuple(plan.get('evidence_ids') or [])))
    decisions = copy.deepcopy(merged['proposed_decisions'])
    decisions = [decision for decision in decisions if
        (decision.get('title'), tuple(decision.get('evidence_ids') or [])) in eligible_plan_ids]
    for decision in decisions:
        source_plan = next((plan for plan in published_plans if plan.get('title') == decision.get('title')
                            and plan.get('evidence_ids') == decision.get('evidence_ids')), None)
        if source_plan:
            decision['evidence_tier'] = source_plan['evidence_tier']
    decisions.sort(key=lambda row: (TIER_ORDER.get(row.get('evidence_tier'), 99),
                                    priority.get(row.get('priority'), 4)))
    published['implementation_plans'] = published_plans
    published['proposed_decisions'] = decisions
    published['recommendation_classification_version'] = CLASSIFICATION_VERSION
    published['recommendation_classification_audit'] = classification_audit
    published['recommendation_engine'] = RECOMMENDATION_ENGINE
    return published

