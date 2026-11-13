"""Keyword-independent specialist finding coverage and two-audience action validation.

A specialist interpretation is not automatically a verified ranking cause. Every
finding must receive a documented disposition, including unsupported findings.
"""
from __future__ import annotations

OUTCOMES = {'action', 'merged', 'investigate', 'deferred'}


def validate_action_coverage(result, packet):
    errors = []
    rows = result.get('finding_dispositions')
    if not isinstance(rows, list):
        return ['finding_dispositions: must be an array']
    findings = {f['id']: f for f in packet.get('specialist_findings', [])}
    fact_ids = {f['id'] for f in packet.get('facts', [])}
    links = packet.get('specialist_fact_links') or {}
    plans = result.get('implementation_plans') or []
    seen = set()
    for i, row in enumerate(rows):
        loc = f'finding_dispositions[{i}]'
        if not isinstance(row, dict):
            errors.append(f'{loc}: must be an object'); continue
        fid = row.get('specialist_finding_id')
        if fid not in findings:
            errors.append(f'{loc}: unknown specialist_finding_id'); continue
        if fid in seen:
            errors.append(f'{loc}: duplicate specialist_finding_id')
        seen.add(fid)
        outcome = row.get('outcome')
        if outcome not in OUTCOMES:
            errors.append(f'{loc}: invalid outcome')
        for key in ('simple_explanation', 'technical_explanation', 'next_step', 'reason'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                errors.append(f'{loc}: missing {key}')
        indices = row.get('plan_indices')
        if not isinstance(indices, list) or any(type(n) is not int or n < 0 or n >= len(plans) for n in indices):
            errors.append(f'{loc}: invalid plan_indices'); indices = []
        if len(indices) != len(set(indices)):
            errors.append(f'{loc}: duplicate plan_indices')
        refs = row.get('evidence_ids')
        if not isinstance(refs, list) or any(ref not in fact_ids for ref in refs):
            errors.append(f'{loc}: invalid evidence_ids'); refs = []
        if not set(refs).issubset(set(links.get(fid, []))):
            errors.append(f'{loc}: evidence_ids not linked to specialist finding')
        if outcome in ('action', 'merged'):
            if not indices:
                errors.append(f'{loc}: actionable finding must link to an implementation plan')
            for n in indices:
                if not isinstance(plans[n], dict) or fid not in (plans[n].get('specialist_finding_ids') or []):
                    errors.append(f'{loc}: linked plan does not cite this specialist finding')
            if not refs:
                errors.append(f'{loc}: actionable finding requires approved factual evidence')
        elif indices:
            errors.append(f'{loc}: investigation or deferred finding must not claim an implementation plan')
    missing = set(findings) - seen
    if missing:
        errors.append('finding_dispositions: missing specialist findings ' + ', '.join(sorted(missing)))
    return errors


def coverage_summary(published):
    rows = published.get('finding_dispositions') or []
    counts = {key: 0 for key in sorted(OUTCOMES)}
    for row in rows:
        if isinstance(row, dict) and row.get('outcome') in counts:
            counts[row['outcome']] += 1
    return {'accounted_for': len(rows), 'by_outcome': counts}
