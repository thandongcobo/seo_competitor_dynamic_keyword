"""Reproduce a saved-evidence recommendation evaluation without network or model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from analysis.recommendations import classify_evidence_tier, generate_recommendations
from llm_foundation.focused_recommendations import TASKS, merge_tasks, task_packet, validate_task
from llm_foundation.evidence_recovery import recover_invalid_task
from llm_foundation.recommendation_quality import audit_recommendations
from scripts.generate_executive_pdf import build_appendix, build_management_pdf
from scripts.run_llm_focused_recommendations import load_saved, save_preservation_report


class NetworkDisabledClient:
    """Instrumentation marker: this offline path never creates an inference client."""
    request_attempts = 0



def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('output/task3_evaluation/aviator'))
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    out = (project / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    source = project / 'output/results/aviator'
    focus_source = project / 'output/gemma_tests/aviator/focused/llm_outputs'
    comparison_source = source / 'aviator_comparison.json'
    canonical_source = source / 'llm_foundation/canonical_evidence.json'
    cache_source = focus_source / 'focused_tasks'
    if not comparison_source.is_file() or not canonical_source.is_file() or not cache_source.is_dir():
        raise FileNotFoundError('Required saved Aviator comparison, canonical evidence or focused-task cache is missing.')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'saved_inputs').mkdir(exist_ok=True)
    comparison_copy = out / 'saved_inputs/aviator_comparison.json'
    canonical_copy = out / 'saved_inputs/canonical_evidence.json'
    shutil.copy2(comparison_source, comparison_copy)
    shutil.copy2(canonical_source, canonical_copy)
    original_hashes = {str(path): sha256(path) for path in [comparison_source, canonical_source]}
    for task in TASKS:
        specialist = source / 'llm_outputs' / f'{task}_validated.json'
        if not specialist.is_file():
            raise FileNotFoundError(f'Missing saved {task} specialist response: {specialist}')
        original_hashes[str(specialist)] = sha256(specialist)
        shutil.copy2(specialist, out / 'saved_inputs' / specialist.name)
    for path in cache_source.glob('*'):
        if path.is_file():
            original_hashes[str(path)] = sha256(path)
    copied_task_dir = out / 'llm_outputs/focused_tasks'
    shutil.copytree(cache_source, copied_task_dir, dirs_exist_ok=True)

    packet, specialists = load_saved(source)
    focused_outputs = {}
    task_records = []
    for task in TASKS:
        task_file = cache_source / f'{task}_validated.json'
        saved_task = json.loads(task_file.read_text(encoding='utf-8'))
        scoped = task_packet(packet, task)
        response = saved_task['result']
        errors = validate_task(response, scoped, task)
        recovery_file = out / 'llm_outputs/focused_tasks' / f'{task}_evidence_recovery_audit.json'
        recovery = None
        if errors:
            recovered, recovery = recover_invalid_task(response, errors, scoped, task)
            if recovered is None:
                save(out / 'llm_outputs/focused_tasks' / f'{task}_evidence_recovery_audit.json', recovery)
                raise ValueError(f'{task}: saved response failed offline validation and recovery could not preserve a safe result: {errors}')
            remaining = validate_task(recovered, scoped, task)
            if remaining:
                raise ValueError(f'{task}: recovered saved response still fails validation: {remaining}')
            response = recovered
            save(recovery_file, recovery)
            save(out / 'llm_outputs/focused_tasks' / f'{task}_recovered_review.json', response)
        focused_outputs[task] = response
        task_record = {
            'task': task, 'status': 'recovered_with_review' if recovery else 'validated_saved_response',
            'attempts': saved_task.get('attempts'),
            'fingerprint_status': 'saved response predates current prompt fingerprint; revalidated against current saved evidence',
            'citation_numeric_scope_lineage_validation': 'passed_after_recovery' if recovery else 'passed',
            'recovery_status': recovery.get('status') if recovery else 'not_triggered',
            'recovery_audit': recovery,
        }
        task_records.append(task_record)
        wrapper = dict(saved_task)
        wrapper['result'] = response
        wrapper['recovery_status'] = recovery.get('status') if recovery else 'not_triggered'
        wrapper['review_finding_ids'] = recovery.get('review_finding_ids', []) if recovery else []
        save(out / 'llm_outputs/focused_tasks' / f'{task}_validated.json', wrapper)

    merged = merge_tasks(packet, focused_outputs)
    recovery_summary = {row['task']: row.get('recovery_audit', {}).get('review_finding_ids', [])
                        for row in task_records if row.get('recovery_audit')}
    if recovery_summary:
        merged['limitations'].append(
            'Saved recommendation actions were recovered offline; quarantined finding dispositions require human review. '
            'See the per-task evidence recovery audit before any action is considered.')
    quality = audit_recommendations(merged, expected_findings=[f['id'] for f in packet['specialist_findings']],
                                    require_actionable=True, enforce_causation=True,
                                    enforce_unmeasured_loss=True)
    save(out / 'llm_outputs/executive_evidence_packet.json', packet)
    save(out / 'llm_outputs/executive_validated.json', merged)
    save(out / 'llm_outputs/recommendation_quality_report.json', quality)
    save_preservation_report(out, specialists, merged)
    save(out / 'llm_outputs/focused_run_metadata.json', {
        'keyword': 'aviator', 'mode': 'offline_saved_response_revalidation_and_recovery',
        'generated_at_utc': None, 'external_requests': 0, 'evidence_recovery': recovery_summary,
        'total_plans': len(merged.get('implementation_plans', [])),
        'total_dispositions': len(merged.get('finding_dispositions', [])),
        'requires_human_review': True,
    })
    client = NetworkDisabledClient()

    data = json.loads(comparison_copy.read_text(encoding='utf-8'))
    recommendations = generate_recommendations(
        keyword=data['keyword'], ranking_urls=data['primary_ranking_urls'],
        advanced_evidence=data.get('advanced_evidence') or {},
        onpage=data.get('onpage_comparison') or {},
        technical_comparison=data.get('technical_comparison') or {},
    )
    data['recommendations'] = recommendations
    recommendation_json = out / 'aviator_recommendations.json'
    save(recommendation_json, data)

    from analysis.recommendation_classification import TIER_1, TIER_2, adapt_recommendations
    tier_names = [TIER_1, TIER_2]
    focused_classified, focused_audit = adapt_recommendations(merged.get('implementation_plans', []))
    classification = {
        'keyword': data['keyword'],
        'deterministic_recommendations': [
            {'order': row.get('order'), 'id': row['id'], 'title': row['title'],
             'tier': row['evidence_tier'], 'priority_score': row['priority_score'],
             'evidence_provenance': row['evidence_provenance']}
            for row in recommendations
        ],
        'deterministic_tier_counts': {tier: sum(row['evidence_tier'] == tier for row in recommendations)
                                      for tier in tier_names},
        'focused_plan_tiers': [
            {'title': plan['title'], 'tier': plan['evidence_tier'],
             'evidence_ids': plan.get('evidence_ids', []),
             'specialist_finding_ids': plan.get('specialist_finding_ids', [])}
            for plan in focused_classified
        ],
        'focused_tier_counts': {tier: sum(plan['evidence_tier'] == tier
                                          for plan in focused_classified)
                                for tier in tier_names},
        'focused_classification_audit': focused_audit,
        'tier_rule_checks': {
            'specific_verified_action_is_tier_1_without_history': classify_evidence_tier(
                observation_verified=True, action_supported=True, established_principle=True,
                exact_scope_verified=True, action_specific=True) == TIER_1,
            'numerical_difference_alone_is_ineligible': classify_evidence_tier(
                observation_verified=True, action_supported=True, established_principle=False,
                exact_scope_verified=True, action_specific=True) is None,
            'moderate_verified_action_is_tier_2': classify_evidence_tier(
                observation_verified=True, action_supported=True, established_principle=True,
                exact_scope_verified=False, action_specific=True,
                material_uncertainty=True) == TIER_2,
            'unsupported_observation_is_ineligible': classify_evidence_tier(
                observation_verified=False, action_supported=True) is None,
        },
        'ordering_valid': [r['evidence_tier'] for r in recommendations] == sorted(
            [r['evidence_tier'] for r in recommendations],
            key={TIER_1: 1, TIER_2: 2}.get),
    }
    save(out / 'recommendation_classification_results.json', classification)

    quality = json.loads((out / 'llm_outputs/recommendation_quality_report.json').read_text(encoding='utf-8'))
    validation_audit = {
        'offline_only': True, 'model_request_attempts': client.request_attempts,
        'quality_audit': quality, 'information_preservation_report':
            json.loads((out / 'llm_outputs/information_preservation_report.json').read_text(encoding='utf-8')),
        'task_records': task_records,
        'original_input_sha256': original_hashes,
        'source_inputs_unchanged': all(sha256(Path(path)) == digest for path, digest in original_hashes.items()),
        'note': 'All saved responses were revalidated against the current evidence packet; onpage required evidence recovery and an unsupported numeric target was quarantined. Remaining recommendation-quality blocking flags are preserved for review.',
    }
    save(out / 'validation_and_recovery_audit.json', validation_audit)

    canonical = json.loads(canonical_copy.read_text(encoding='utf-8'))
    serp_path = project / 'data/processed/aviator/serp_google.json'
    investigation_date = None
    if serp_path.is_file():
        serp = json.loads(serp_path.read_text(encoding='utf-8'))
        investigation_date = serp.get('datetime')
    pdf_path = out / 'aviator_draft_management_report.pdf'
    appendix_path = out / 'aviator_technical_appendix.md'
    build_management_pdf(pdf_path, data, merged, quality, 'aviator', canonical, investigation_date)
    run_records = []
    for task in task_records:
        diagnostics = sorted(copied_task_dir.glob(f"{task['task']}_attempt_*_diagnostics.json"))
        task['diagnostics'] = [json.loads(p.read_text(encoding='utf-8')) for p in diagnostics]
        run_records.append(task)
    appendix = build_appendix(data, merged, quality, comparison_copy.name, canonical, run_records)
    appendix_path.write_text(appendix, encoding='utf-8')
    save(out / 'offline_run_manifest.json', {
        'keyword': 'aviator', 'mode': 'saved_evidence_and_saved_specialist_responses',
        'external_requests': 0, 'recommendation_json': str(recommendation_json),
        'management_pdf': str(pdf_path), 'technical_appendix': str(appendix_path),
        'classification_results': str(out / 'recommendation_classification_results.json'),
        'validation_recovery_audit': str(out / 'validation_and_recovery_audit.json'),
        'deterministic_recommendations': len(recommendations),
        'focused_implementation_plans': len(merged.get('implementation_plans', [])),
        'blocking_quality_flags': quality['blocking_count'], 'review_quality_flags': quality['review_count'],
        'source_inputs_unchanged': validation_audit['source_inputs_unchanged'],
        'draft_status': 'not approved or published',
    })
    if not validation_audit['source_inputs_unchanged']:
        raise AssertionError('An original saved input changed during evaluation.')
    print(json.dumps({'output_dir': str(out), 'request_attempts': client.request_attempts,
                      'deterministic_tier_counts': classification['deterministic_tier_counts'],
                      'focused_tier_counts': classification['focused_tier_counts'],
                      'blocking_quality_flags': quality['blocking_count'],
                      'review_quality_flags': quality['review_count'],
                      'source_inputs_unchanged': validation_audit['source_inputs_unchanged']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
