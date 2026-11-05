"""Lossless specialist lineage and actionable proposal validation.

Specialist text is preserved verbatim, but is NOT promoted to a verified fact.
Fact IDs are the only approved quantitative evidence for executive claims.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

TASKS = ('onpage', 'backlinks', 'technical', 'competition')


def specialist_records(outputs):
    records = []
    for task in TASKS:
        output = outputs.get(task) or {}
        for index, finding in enumerate(output.get('findings') or [], 1):
            original = copy.deepcopy(finding)
            digest = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
            records.append({'id': f'{task.upper()}_{index:02d}', 'task': task,
                            'source_sha256': digest, 'finding': original,
                            'source': f'llm_outputs/{task}_validated.json#/findings/{index-1}',
                            'status': 'specialist_interpretation_not_independently_verified'})
    return records


def validate_plans(plans, packet):
    """Reject unknown citations, missing procedures, and invented specialist IDs."""
    if not isinstance(plans, list):
        return ['implementation_plans must be an array']
    fact_ids = {x['id'] for x in packet.get('facts', [])}
    specialist_ids = {x['id'] for x in packet.get('specialist_findings', [])}
    errors = []
    if len(plans) > 20:
        errors.append('Too many implementation plans (maximum 20)')
    for i, plan in enumerate(plans):
        if not isinstance(plan, dict):
            errors.append(f'plan {i}: not an object'); continue
        for field in ('title', 'rationale', 'owner', 'priority', 'success_measure', 'uncertainty'):
            if not isinstance(plan.get(field), str) or not plan[field].strip():
                errors.append(f'plan {i}: missing {field}')
        steps = plan.get('implementation_steps')
        if not isinstance(steps, list) or not steps or len(steps) > 15 or any(not isinstance(s, str) or not s.strip() for s in steps):
            errors.append(f'plan {i}: implementation_steps must have 1-15 nonempty strings')
        refs = plan.get('evidence_ids')
        if not isinstance(refs, list) or not refs or any(r not in fact_ids for r in refs):
            errors.append(f'plan {i}: invalid evidence_ids')
        source_refs = plan.get('specialist_finding_ids')
        if not isinstance(source_refs, list) or not source_refs or any(r not in specialist_ids for r in source_refs):
            errors.append(f'plan {i}: invalid specialist_finding_ids')
        if plan.get('priority') not in ('high', 'medium', 'low', 'investigate'):
            errors.append(f'plan {i}: invalid priority')
    return errors


def build_preservation_report(specialists, published):
    original = specialist_records(specialists)
    retained = published.get('specialist_findings') or []
    original_map = {x['id']: x['source_sha256'] for x in original}
    retained_map = {x.get('id'): x.get('source_sha256') for x in retained if isinstance(x, dict)}
    missing = [key for key, digest in original_map.items() if retained_map.get(key) != digest]
    plans = published.get('implementation_plans') or []
    referenced = {key for p in plans if isinstance(p, dict) for key in p.get('specialist_finding_ids', [])}
    from .action_coverage import coverage_summary
    dispositions = published.get('finding_dispositions') or []
    disposition_ids = {row.get('specialist_finding_id') for row in dispositions if isinstance(row, dict)}
    return {'finding_action_coverage': coverage_summary(published),
            'findings_without_disposition': sorted(original_map.keys() - disposition_ids),
            'original_specialist_findings': len(original), 'retained_specialist_findings': len(retained),
            'missing_or_changed_ids': missing, 'all_original_findings_preserved': not missing and len(original) == len(retained),
            'findings_referenced_by_implementation_plans': sorted(referenced & original_map.keys()),
            'findings_without_implementation_plans': sorted(original_map.keys() - referenced),
            'implementation_plan_count': len(plans)}


def save_preservation_report(results_dir: Path, specialists: dict, published: dict):
    report = build_preservation_report(specialists, published)
    path = Path(results_dir) / 'llm_outputs' / 'information_preservation_report.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
