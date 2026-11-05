"""Conservative, run-scoped evidence reanalysis and partial recovery.

Never accepts an unsupported claim. When targeted model retries cannot fix a
localized numeric/citation problem, isolate the affected plans/findings for
human investigation, keep unrelated validated work, and preserve originals.
No collectors, network calls, keyword/domain exceptions, or new measurements.
"""
from __future__ import annotations

import copy
import re
from decimal import Decimal
from .grounded_retry import diagnose_errors

_PLAN = re.compile(r'^implementation_plans\[(\d+)\](?:\.|:|$)')
_DISPOSITION = re.compile(r'^finding_dispositions\[(\d+)\](?:\.|:|$)')
_PLAN_ALIAS = re.compile(r'^plan (\d+):')


def build_evidence_registry(scoped):
    """Index numeric source values by fact, side, metric, unit and exact path.

    Values are only observations: matching a number does NOT prove the model
    described the right metric, website, or source scope.
    """
    records = []
    identities = {'ours': (scoped.get('tracked') or {}).get('url'),
                  'benchmark': (scoped.get('benchmark') or {}).get('url')}

    def visit(value, fact_id, path, side=None):
        if type(value) in (int, float, Decimal):
            metric = path[-1] if path else 'value'
            unit = ('ms' if metric.endswith('_ms') else
                    'count' if any(word in metric for word in ('backlink', 'domain', 'count', 'position', 'rank')) else
                    'score_or_ratio' if any(word in metric for word in ('score', 'jaccard', 'ratio')) else
                    'unspecified')
            records.append({'fact_id': fact_id, 'path': '.'.join(path), 'value': value,
                            'metric': metric, 'unit': unit, 'side': side,
                            'source_url': ((scoped.get('tracked') or {}).get('domain') if side == 'ours' else
                                           (scoped.get('benchmark') or {}).get('domain')) if fact_id == 'BL_DOMAIN' else identities.get(side),
                            'captured_at': scoped.get('collected_at') or scoped.get('captured_at'),
                            'scope': ('domain' if fact_id == 'BL_DOMAIN' else
                                      'page' if fact_id in ('BL_PAGE', 'ON_LINKS', 'ON_TITLE') else
                                      'search' if fact_id in ('SERP', 'KW_SHARED', 'KW_QUERY_GAPS') else 'other')})
        elif isinstance(value, dict):
            for key, child in value.items():
                visit(child, fact_id, path + [str(key)], key if key in identities else side)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, fact_id, path + [str(i)], side)

    for fact in scoped.get('facts') or []:
        if isinstance(fact, dict) and isinstance(fact.get('id'), str):
            visit(fact.get('values'), fact['id'], [])
    return records


def _review_disposition(row, scoped):
    fid = row['specialist_finding_id']
    permitted = set((scoped.get('specialist_fact_links') or {}).get(fid, []))
    available = {f['id'] for f in scoped.get('facts', [])}
    refs = [f for f in (row.get('evidence_ids') or []) if f in permitted and f in available]
    return {
        'specialist_finding_id': fid, 'outcome': 'investigate', 'plan_indices': [],
        'simple_explanation': 'A proposed explanation could not be verified against the saved evidence. Further review is needed.',
        'technical_explanation': 'Recheck the original source measurement, metric scope and cited evidence before approving a change.',
        'next_step': 'Review the saved source records and rerun the scoped comparison if new data is authorized and required.',
        'reason': 'The original recommendation contained an unresolved factual or citation validation issue.',
        'evidence_ids': refs,
    }


def recover_invalid_task(response, errors, scoped, task):
    """Return (validated_candidate_or_None, audit). Fail closed on unknown errors.

    Quarantine a whole connected plan/finding group if a claim cannot be safely
    repaired. Original model text is retained separately in the audit, not
    silently removed or reinterpreted as a verified fact.
    """
    audit = {'schema_version': '1.0', 'task': task, 'status': 'not_recovered',
             'original_errors': list(errors), 'registry': build_evidence_registry(scoped),
             'diagnostics': diagnose_errors(errors, response, scoped),
             'quarantined_plans': [], 'quarantined_dispositions': []}
    if not isinstance(response, dict) or set(response) != {
            'schema_version', 'task', 'implementation_plans', 'finding_dispositions'}:
        audit['reason'] = 'Malformed task schema; no safe partial recovery'
        return None, audit
    if response.get('schema_version') != '1.0' or response.get('task') != task:
        audit['reason'] = 'Wrong task identity'
        return None, audit
    plans = response['implementation_plans']
    dispositions = response['finding_dispositions']
    expected = {f['id'] for f in scoped.get('specialist_findings', [])}
    if (not isinstance(plans, list) or not isinstance(dispositions, list) or
        any(not isinstance(p, dict) for p in plans) or
        any(not isinstance(d, dict) for d in dispositions) or
        len(dispositions) != len(expected) or
        {d.get('specialist_finding_id') for d in dispositions} != expected or
        len({d.get('specialist_finding_id') for d in dispositions}) != len(dispositions)):
        audit['reason'] = 'Missing, duplicate, or malformed specialist coverage'
        return None, audit
    # When ONLY an explanatory disposition field contains an unsupported number,
    # retain its otherwise validated plan. Replace the invalid explanation with
    # a source-check instruction, retain the exact original in the audit, and
    # re-run every strict validator. Never change a measured value or plan target.
    isolated = []
    for error in errors:
        match = re.match(r'^finding_dispositions\[(\d+)\]\.(reason|next_step): numeric claim ', str(error))
        if not match:
            isolated = []
            break
        index, field = int(match.group(1)), match.group(2)
        if index >= len(dispositions):
            isolated = []
            break
        pair = (index, field)
        if pair not in isolated:
            isolated.append(pair)
    if isolated:
        candidate = copy.deepcopy(response)
        for index, field in isolated:
            original = candidate['finding_dispositions'][index][field]
            candidate['finding_dispositions'][index][field] = (
                'Review the approved source records and confirm that this recommendation is justified; '
                'the original numerical assertion was not verified.' if field == 'reason' else
                'Recheck the cited source evidence and confirm the appropriate next action before implementation.')
            audit.setdefault('sanitized_fields', []).append({
                'path': f'finding_dispositions[{index}].{field}', 'original': original,
                'replacement': candidate['finding_dispositions'][index][field]})
        from .focused_recommendations import validate_task
        remaining = validate_task(candidate, scoped, task)
        if not remaining:
            audit['status'] = 'recovered_with_review'
            audit['review_finding_ids'] = sorted({dispositions[i]['specialist_finding_id'] for i, _ in isolated})
            audit['preserved_plan_count'] = len(plans)
            audit['original_plan_count'] = len(plans)
            return candidate, audit
        audit['sanitized_fields_validation_errors'] = remaining
    bad_plans, bad_dispositions = set(), set()
    for error in errors:
        msg = str(error)
        m = _PLAN.match(msg) or _PLAN_ALIAS.match(msg)
        d = _DISPOSITION.match(msg)
        if m:
            idx = int(m.group(1))
            if idx >= len(plans):
                audit['reason'] = 'Invalid plan error location'; return None, audit
            bad_plans.add(idx)
        elif d:
            idx = int(d.group(1))
            if idx >= len(dispositions):
                audit['reason'] = 'Invalid disposition error location'; return None, audit
            bad_dispositions.add(idx)
        else:
            audit['reason'] = 'Unlocalized validation error: ' + msg[:200]
            return None, audit
    if not bad_plans and not bad_dispositions:
        audit['reason'] = 'No localized error to recover'; return None, audit
    # Find all connected plans and findings. Avoid leaving orphan plans or
    # actions linked to quarantined content; never delete unrelated findings.
    changed = True
    while changed:
        before = (len(bad_plans), len(bad_dispositions))
        for i in tuple(bad_dispositions):
            for idx in dispositions[i].get('plan_indices') or []:
                if type(idx) is not int or idx < 0 or idx >= len(plans):
                    audit['reason'] = 'Invalid plan reference'; return None, audit
                bad_plans.add(idx)
        for i, row in enumerate(dispositions):
            if (any(idx in bad_plans for idx in (row.get('plan_indices') or [])) or
                any(row.get('specialist_finding_id') in (plans[idx].get('specialist_finding_ids') or [])
                    for idx in bad_plans)):
                bad_dispositions.add(i)
        changed = (len(bad_plans), len(bad_dispositions)) != before
    kept = [i for i in range(len(plans)) if i not in bad_plans]
    index_map = {old: new for new, old in enumerate(kept)}
    candidate = copy.deepcopy(response)
    candidate['implementation_plans'] = [copy.deepcopy(plans[i]) for i in kept]
    candidate['finding_dispositions'] = []
    for i, row in enumerate(dispositions):
        if i in bad_dispositions:
            candidate['finding_dispositions'].append(_review_disposition(row, scoped))
            audit['quarantined_dispositions'].append({'index': i, 'original': copy.deepcopy(row)})
        else:
            copy_row = copy.deepcopy(row)
            try:
                copy_row['plan_indices'] = [index_map[idx] for idx in row.get('plan_indices') or []]
            except (KeyError, TypeError):
                audit['reason'] = 'Invalid preserved plan reference'; return None, audit
            candidate['finding_dispositions'].append(copy_row)
    audit['quarantined_plans'] = [{'index': i, 'original': copy.deepcopy(plans[i])} for i in sorted(bad_plans)]
    # Never bypass the original validators. Import lazily to avoid cycles.
    from .focused_recommendations import validate_task
    remaining = validate_task(candidate, scoped, task)
    if remaining:
        audit['reason'] = 'Reanalysed candidate still fails strict validation'
        audit['remaining_errors'] = remaining
        return None, audit
    audit['status'] = 'recovered_with_review'
    audit['review_finding_ids'] = [dispositions[i]['specialist_finding_id'] for i in sorted(bad_dispositions)]
    audit['preserved_plan_count'] = len(candidate['implementation_plans'])
    audit['original_plan_count'] = len(plans)
    return candidate, audit
