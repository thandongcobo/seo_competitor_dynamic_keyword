"""Conservative, keyword-independent quality audit for focused SEO recommendations.

This supplements (never replaces) evidence/citation validation. It does not edit LLM
outputs. Heuristics flag reasoning and implementation risks for human review;
blocking issues can optionally stop publication in strict mode.
"""
from __future__ import annotations

import re
from collections import Counter

QUALITY_VERSION = '1.2'


def _issue(issues, severity, code, path, message, next_check):
    issues.append({'severity': severity, 'code': code, 'path': path,
                   'message': message, 'next_check': next_check})


def _text(*items):
    return ' '.join(str(x) for x in items if isinstance(x, str))


# Outgoing links counted ON a page are not incoming links TO that page.
# This detector flags unsupported inferences but permits a clearly separate,
# proposed incoming-link investigation. It never treats that investigation as
# already measured evidence.
_INBOUND_PHRASE = re.compile(
    r'\b(?:high.authority pages.{0,130}?link to|links? pointing to|link equity flow|page authority distribution)\b',
    re.I,
)
_SEPARATE_AUDIT = re.compile(
    r'\b(?:separat(?:e|ely)|independen(?:t|tly)|distinct|additional|new)\b.{0,115}'
    r'\b(?:incoming|inbound|links? to|crawl|audit)\b|'
    r'\b(?:incoming|inbound)\b.{0,100}\b(?:audit|crawl|inspect|measure|map|collect|verify)\b|'
    r'\b(?:incoming|inbound)\s+links?\s+audit\b', re.I,
)
_INVESTIGATE = re.compile(r'\b(?:identify|investigat|audit|crawl|inspect|collect|map|verify|review|assess|measure|propos|potential|could)\w*\b', re.I)
_NOT_INFER = re.compile(
    r'\b(?:do not|cannot|must not|should not|never)\s+(?:be\s+)?(?:infer|imply|establish|prove|indicate|demonstrate)\w*\b|'
    r'\b(?:cannot|should not|must not)\s+be\s+(?:inferred|assumed)\b|'
    r'\b(?:does not|do not)\s+(?:measure|establish|prove)\b', re.I,
)
_OUTGOING_DESTINATION = re.compile(
    r'\blinks? pointing to\s+(?:other|related|additional|different)\s+(?:parts|pages|sections|content|areas|resources)\b', re.I,
)


def internal_link_direction_matches(plan):
    """Return precise editable-field matches that imply unsupported incoming links.

    This is a conservative lexical check, not a semantic proof. A separate
    incoming-link audit is permissible, but outgoing counts cannot justify
    assertions of inbound volume or link-equity improvement.
    """
    if 'ON_LINKS' not in set(plan.get('evidence_ids') or []):
        return []
    findings = []
    fields = ('title', 'rationale', 'simple_explanation', 'technical_explanation',
              'uncertainty', 'success_measure')
    fields_and_values = [(key, plan.get(key)) for key in fields]
    fields_and_values.extend((f'implementation_steps[{i}]', step)
                             for i, step in enumerate(plan.get('implementation_steps') or []))
    for field, value in fields_and_values:
        if not isinstance(value, str):
            continue
        for match in _INBOUND_PHRASE.finditer(value):
            phrase = match.group(0)
            local = value[max(0, match.start()-125):min(len(value), match.end()+190)]
            # Outgoing links to OTHER parts of the same site are directly in
            # scope of the page-level outgoing link count.
            if phrase.lower().startswith('link') and _OUTGOING_DESTINATION.search(local):
                continue
            # Explicitly denying a measurement/inference is safe.
            if _NOT_INFER.search(local):
                continue
            # Only allow inbound *investigations*, not unmeasured inbound claims.
            # Require an independently described audit in the same field.
            if ('link equity flow' not in phrase.lower() and
                    'page authority distribution' not in phrase.lower() and
                    (_INVESTIGATE.search(value[max(0, match.start()-95):match.end()]) and
                     _SEPARATE_AUDIT.search(local))):
                continue
            findings.append({'field': field, 'matched_phrase': phrase,
                             'context': local})
    return findings



# Scope-aware checks. These are conservative textual warnings, not proof of
# causal SEO effects. No keyword, domain, ranking URL or specialist ID is fixed.
_UNMEASURED_LOSS = re.compile(
    r'\b(?:losing|lost)\s+(?:(?:many|significant|substantial|more)\s+)?'
    r'(?:users|visitors|customers|traffic|clicks)\b', re.I)
_CONTENT_ACTION = re.compile(r'\b(?:create|develop|expand|publish|rewrite|launch|improve)\b', re.I)
_CONTENT_OBJECT = re.compile(r'\b(?:content|guide|article|page|section|faq|topic|cluster)\b', re.I)
_QUERY_URL = re.compile(r'\b(?:exact|actual|query.specific|each|per.query)\b.{0,95}'
                        r'\b(?:ranking|ranked)\s+(?:url|page|landing\s+page)s?\b|'
                        r'\b(?:ranking|ranked)\s+(?:url|page|landing\s+page)s?\b.{0,95}'
                        r'\b(?:each|per.query|query.specific|exact|actual)\b', re.I)
_URL_CHECK = re.compile(r'\b(?:verify|confirm|identify|inspect|map|check|audit|collect|determine)\b', re.I)
_INTENT_CHECK = re.compile(r'\b(?:intent|purpose|existing\s+content|cannibali[sz])\b', re.I)
_CHANGE = re.compile(r'\b(?:implement|deploy|publish|remove|defer|update|launch|rewrite|create|replace|ship|enable|disable|add)\b', re.I)
_VERIFY = re.compile(
    r'\b(?:verif(?:y|ied|ication)|test|monitor|(?:re[- ]?)?measur(?:e|ed|es|ing|ement|ements)|'
    r'compare|audit|retest|check|validat(?:e|ed|ion)|recrawl|repeat|confirm(?:ed|ation)?)\b', re.I)

_POST = re.compile(r'\b(?:after|post[- ](?:deployment|release|change)|following|deployed|released|implementation|before.and.after)\b', re.I)
_SCRIPT = re.compile(r'\b(?:javascript|script|bundle|third.party|code.splitt|resource\s+load)\b', re.I)
_SAFEGUARD = re.compile(r'\b(?:security|fraud|regression|rollback|core\s+(?:user\s+)?flows?|functionality|consent|tracking|feature\s+test|business.critical)\b', re.I)
_PROMISE = re.compile(r'\b(?:will|guaranteed|definitely|certainly|must)\b.{0,70}\b(?:improve|increase|boost|rankings?|traffic|clicks?)\b', re.I)
_QUALIFIER = re.compile(r'\b(?:unverified|uncertain|unknown|not\s+guaranteed|cannot\s+guarantee|no\s+proof|not\s+proven|may\s+not)\b', re.I)
_ACTION_VERB = re.compile(r'\b(?:replace|rewrite|revise|update|add|remove|configure|defer|preload|compress|resize|split|lazy.load|link|publish|implement|refactor|earn|improve|preserve|retain|serve|render|move|consolidate|merge|clarify|expand|change|ship|deploy|create|profile|optimi[sz]e|reduce|set|write|correct|restructure|surface|include|remove|separate)\b', re.I)
_VAGUE_PLAN = re.compile(r'^\s*(?:investigate|review|audit|analyse|analyze|assess|explore|consider|examine|check|look into|monitor)\b', re.I)
_CAUSE_CLAIM = re.compile(r'\b(?:causes?|caused|because of|results? in|leads? to|drives?|explains?)\b.{0,80}\b(?:rank(?:ing)?s?|position|visibility|traffic|clicks?)\b|\b(?:rank(?:ing)?s?|position|visibility|traffic|clicks?)\b.{0,80}\b(?:caused by|is due to|results from)\b', re.I)
_UNSUPPORTED_TARGET = re.compile(r'\b(?:increase|grow|reach|achieve|reduce|improve)\b.{0,55}\b(?:by\s+\d+|to\s+\d+|\d+\s*(?:%|percent|links?|domains?|words?|queries?|pages?|seconds?|ms))\b', re.I)


def unmeasured_loss_fields(plan):
    """Return editable field paths containing claims of measured user loss."""
    fields = []
    for name in ('title', 'rationale', 'simple_explanation', 'technical_explanation',
                 'uncertainty', 'success_measure'):
        if _UNMEASURED_LOSS.search(str(plan.get(name) or '')):
            fields.append(name)
    for i, step in enumerate(plan.get('implementation_steps') or []):
        if _UNMEASURED_LOSS.search(str(step)):
            fields.append(f'implementation_steps[{i}]')
    return fields


def query_scope_ready(plan):
    """Require exact query-ranking URLs and intent *before* commissioning content."""
    steps = [str(s) for s in plan.get('implementation_steps') or []]
    first_content = next((i for i, s in enumerate(steps)
                          if _CONTENT_ACTION.search(s) and _CONTENT_OBJECT.search(s)), None)
    if first_content is None:
        return True  # investigation-only recommendations need no content gate
    before = steps[:first_content]
    # A single ordered instruction can be valid ("Verify ... before creating ...").
    # It must explicitly put the URL/intent check before the content action.
    same_step = steps[first_content]
    if (re.search(r'\bbefore\b', same_step, re.I) and
            _URL_CHECK.search(same_step) and _QUERY_URL.search(same_step) and
            _INTENT_CHECK.search(same_step)):
        before.append(same_step)
    return (any(_URL_CHECK.search(s) and _QUERY_URL.search(s) for s in before)
            and any(_INTENT_CHECK.search(s) for s in before))


def missing_post_change_verification(plan):
    """Detect plans that change a site but never verify after the final change."""
    steps = [str(s) for s in plan.get('implementation_steps') or []]
    changed = [i for i, s in enumerate(steps) if _CHANGE.search(s)]
    if not changed:
        return False
    last = changed[-1]
    return not any(_VERIFY.search(s) and (_POST.search(s) or i > last)
                   for i, s in enumerate(steps) if i >= last)


def missing_technical_safeguards(plan):
    steps = [str(s) for s in plan.get('implementation_steps') or []]
    prose = _text(plan.get('title'), plan.get('technical_explanation'), *steps)
    return bool(_SCRIPT.search(prose) and any(_CHANGE.search(s) for s in steps)
                and not _SAFEGUARD.search(prose))


def audience_mismatch(plan):
    """Flag categorical business promises contradicted by technical caveats."""
    simple = str(plan.get('simple_explanation') or '')
    technical = _text(plan.get('technical_explanation'), plan.get('uncertainty'))
    return bool(_PROMISE.search(simple) and _QUALIFIER.search(technical))

def audit_recommendations(result, *, expected_findings=None, require_actionable=False,
                          enforce_causation=True, enforce_unmeasured_loss=True):
    """Return a lossless, deterministic audit; never rewrite recommendations.

    `expected_findings` is an optional iterable of current investigation IDs.
    All checks use evidence scope and generic language patterns, never a keyword,
    brand, exact URL or fixed specialist finding ID.
    """
    issues = []
    plans = result.get('implementation_plans') or []
    rows = result.get('finding_dispositions') or []
    if not isinstance(plans, list) or not isinstance(rows, list):
        _issue(issues, 'blocking', 'invalid_structure', '$', 'Plans/dispositions must be arrays.', 'Check output schema.')
        return _report(issues, 0, 0)

    ids = [r.get('specialist_finding_id') for r in rows if isinstance(r, dict)]
    if expected_findings is not None:
        expected = set(expected_findings)
        missing = expected - set(ids)
        if missing:
            _issue(issues, 'blocking', 'missing_findings', 'finding_dispositions',
                   'Some original specialist findings are not accounted for.',
                   'Restore dispositions for all current investigation finding IDs: ' + ', '.join(sorted(missing)))
    if len(ids) != len(set(ids)):
        _issue(issues, 'blocking', 'duplicate_findings', 'finding_dispositions',
               'A specialist finding appears more than once.', 'Give each finding exactly one outcome.')

    for i, plan in enumerate(plans):
        if not isinstance(plan, dict):
            _issue(issues, 'blocking', 'invalid_plan', f'implementation_plans[{i}]',
                   'Implementation plan must be an object.', 'Regenerate or repair this plan only.')
            continue
        path = f'implementation_plans[{i}]'
        evidence = set(plan.get('evidence_ids') or [])
        steps = plan.get('implementation_steps') or []
        claim_prose = _text(plan.get('title'), plan.get('rationale'), plan.get('simple_explanation'),
                            plan.get('technical_explanation'), plan.get('uncertainty'))
        prose = _text(claim_prose, *steps)
        # Numeric verification is handled by the existing strict evidence validator.
        if re.search(r'\b(?:necessary|required|essential)\s+to\s+(?:improve|increase|achieve|secure)\b.{0,65}\b(?:rank|ranking|position|traffic|click)', prose, re.I):
            _issue(issues, 'blocking', 'unproven_necessity', path,
                   'Plan presents a proposed change as necessary for a ranking/traffic result.',
                   'Describe a testable hypothesis; do not claim ranking causation.')
        if re.search(r'\b(?:indicates|proves|demonstrates|confirms)\s+(?:a\s+)?(?:lack|deficienc|insufficient|poor)\b.{0,75}\b(?:content|relevan|authorit|depth)', prose, re.I):
            _issue(issues, 'blocking', 'unsupported_quality_inference', path,
                   'An observed metric is treated as proof of content or authority quality.',
                   'Verify exact ranking URLs and assess content/user intent independently.')
        if internal_link_direction_matches(plan):
            _issue(issues, 'blocking', 'internal_link_direction', path,
                   'Links counted on a page are being used to infer links pointing into it or authority flow.',
                   'Separate outgoing links on the captured page from incoming internal links to that URL.')
        if enforce_causation and _CAUSE_CLAIM.search(claim_prose):
            _issue(issues, 'blocking', 'unsupported_causal_ranking_claim', path,
                   'Recommendation states an observed difference as a cause of rankings or traffic.',
                   'Reframe as a testable hypothesis and state that observed differences do not establish causation.')
        if require_actionable and _UNSUPPORTED_TARGET.search(' '.join(str(plan.get(key) or '') for key in
                                               ('title', 'rationale', 'simple_explanation',
                                                'technical_explanation', 'success_measure', 'uncertainty'))):
            _issue(issues, 'blocking', 'arbitrary_implementation_target', path,
                   'Recommendation sets a numeric implementation target that may not be supported by evidence.',
                   'Remove arbitrary quotas; use a measurable verification condition without a preset quantity.')
        concrete_action = any(_ACTION_VERB.search(str(step)) for step in steps)
        if require_actionable and (not concrete_action or
                (_VAGUE_PLAN.search(str(plan.get('title') or '')) and
                 not any(_ACTION_VERB.search(str(step)) and not _VAGUE_PLAN.search(str(step)) for step in steps))):
            _issue(issues, 'blocking', 'generic_non_actionable_plan', path,
                   'Plan lacks a preferred concrete improvement and reads as an investigation task.',
                   'Name one supported change to make; keep checks as prerequisites or post-change verification.')
        if (enforce_unmeasured_loss or result.get('_enforce_user_loss_check')) and unmeasured_loss_fields(plan):
            _issue(issues, 'blocking', 'unmeasured_user_loss', path,
                   'A plan describes lost users/traffic without evidence of measured loss.',
                   'Describe observed search visibility and qualify possible traffic effects.')
        if 'KW_QUERY_GAPS' in evidence and not query_scope_ready(plan):
            _issue(issues, 'review', 'domain_rank_scope', path,
                   'Domain-level keyword positions may belong to different ranking URLs.',
                   'Identify exact ranking URLs for each query and verify intent BEFORE proposing new content.')
        if missing_post_change_verification(plan):
            _issue(issues, 'review', 'missing_post_change_verification', path,
                   'The plan changes a website without an explicit post-change verification step.',
                   'Add a repeatable post-deployment check after the final change.')
        if missing_technical_safeguards(plan):
            _issue(issues, 'review', 'missing_technical_safeguards', path,
                   'Script or bundle changes lack an explicit functionality/security safeguard.',
                   'Test business-critical functionality, security, consent and rollback where relevant.')
        if audience_mismatch(plan):
            _issue(issues, 'review', 'audience_explanation_mismatch', path,
                   'The business explanation promises an outcome that the technical explanation qualifies.',
                   'Use the same evidence scope and uncertainty in both explanations.')
        promise_matches = list(re.finditer(r'\b(?:guarantee|will ensure|to capture)\b.{0,55}\b(?:rich snippets?|ranking|traffic|clicks?)\b', prose, re.I))
        if any(not re.search(r'\b(?:not|never|cannot|does not|do not)\s+$', prose[max(0, m.start()-18):m.start()], re.I) for m in promise_matches):
            _issue(issues, 'review', 'guaranteed_serp_feature', path,
                   'Search features or outcomes are described as guaranteed.',
                   'Treat structured-data eligibility and Google display as conditional.')
        if len(steps) < 3:
            _issue(issues, 'review', 'thin_procedure', path,
                   'Fewer than three implementation steps.',
                   'Specify investigation, controlled change, and post-change verification.')
        if not any(re.search(r'\b(?:verify|test|retest|validate|monitor|compare|audit|measure|recrawl|repeat|check)\b', str(step), re.I) for step in steps):
            _issue(issues, 'review', 'missing_verification_step', path,
                   'Implementation steps omit a verification activity.',
                   'Add a concrete before/after check with repeatable conditions.')
        if not re.search(r'\b(?:if|before|after|subject to|dependent|verify|test|confirm|approval|review)\b', prose, re.I):
            _issue(issues, 'review', 'no_precondition', path,
                   'Plan has no explicit verification or implementation precondition.',
                   'State what must be verified before deployment.')
        if len(str(plan.get('technical_explanation') or '').strip()) < 100:
            _issue(issues, 'review', 'thin_technical_explanation', path,
                   'Technical explanation may be too brief to support implementation.',
                   'Explain the mechanism, affected scope, dependencies, and acceptance criteria.')
        if len(str(plan.get('simple_explanation') or '').strip()) < 45:
            _issue(issues, 'review', 'thin_business_explanation', path,
                   'Plain-language explanation may be too brief.',
                   'Explain the difference, business implication, proposed action and uncertainty.')

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        path = f'finding_dispositions[{i}]'
        prose = _text(row.get('simple_explanation'), row.get('technical_explanation'), row.get('reason'))
        if (enforce_unmeasured_loss or result.get('_enforce_user_loss_check')) and re.search(r'\b(?:losing|lost)\s+(?:many\s+)?(?:users|customers|visitors|traffic|clicks)\b', prose, re.I):
            _issue(issues, 'blocking', 'unmeasured_user_loss', path,
                   'Ranking observations do not establish actual lost visitors or traffic.',
                   'Use qualified visibility language until measured clicks/traffic are available.')
        if re.search(r'\b(?:why they rank higher|why (?:it|they) rank|cause(?:s|d)? (?:the )?rank)\b', prose, re.I):
            _issue(issues, 'review', 'causality_language', path,
                   'Language may imply that an observed difference explains ranking causation.',
                   'Distinguish hypothesis from verified causal evidence.')
        if row.get('outcome') in ('investigate', 'deferred') and not str(row.get('reason') or '').strip():
            _issue(issues, 'review', 'undocumented_unresolved_finding', path,
                   'Unresolved finding has no documented reason.',
                   'State which evidence is missing or why the proposed change is not justified.')

    if not result.get('key_findings') and not result.get('verified_factual_findings'):
        _issue(issues, 'review', 'missing_report_findings', 'key_findings',
               'No executive findings are available for the report section.',
               'Use verified factual findings or omit the empty report section.')
    return _report(issues, len(plans), len(rows))


def _report(issues, plans, dispositions):
    counts = Counter(x['severity'] for x in issues)
    return {'schema_version': QUALITY_VERSION,
            'status': 'review_required' if issues else 'passed',
            'blocking_count': counts['blocking'], 'review_count': counts['review'],
            'plans_audited': plans, 'dispositions_audited': dispositions,
            'issues': issues,
            'note': 'Heuristic quality checks are not proof of SEO causation or technical correctness. Original output is unchanged.'}
