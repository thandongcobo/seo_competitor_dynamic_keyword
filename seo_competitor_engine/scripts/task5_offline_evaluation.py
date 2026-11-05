"""Task 5 offline precision, recovery and reporting integration evaluation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis.recommendations import reconcile_recommendations
from scripts.generate_executive_pdf import build_appendix, build_management_pdf
from scripts.task4_offline_evaluation import main as run_task4


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('output/task5_evaluation/aviator'))
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    out = (project / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    run_task4(['--output-dir', str(out / 'offline')])
    comparison_path = out / 'offline/pipeline/aviator_comparison.json'
    data = json.loads(comparison_path.read_text(encoding='utf-8'))
    specialist = json.loads((out / 'offline/saved_inputs/executive_validated_rechecked.json').read_text(encoding='utf-8'))
    quality = json.loads((out / 'offline/saved_inputs/recommendation_quality_report.json').read_text(encoding='utf-8'))
    # Compare against the saved Task 4 output. The offline rerun uses current
    # code and may already contain Task 5's technical recommendation split.
    task4_artifact = project / 'output/task4_evaluation/aviator/pipeline/aviator_comparison.json'
    previous_task4_recommendations = list(json.loads(task4_artifact.read_text(encoding='utf-8')).get('recommendations') or [])
    original_recommendations = list(data.get('recommendations') or [])
    authoritative, reconciliation = reconcile_recommendations(original_recommendations, specialist, quality)
    data['recommendations'] = authoritative
    data['recommendation_reconciliation_audit'] = reconciliation
    save(comparison_path, data)

    issues_by_plan = {}
    for issue in quality.get('issues', []):
        import re
        match = re.match(r'implementation_plans\[(\d+)\]', issue.get('path', ''))
        if match:
            issues_by_plan.setdefault(int(match.group(1)), []).append(issue)
    blocker_audit = []
    for index, plan in enumerate(specialist.get('implementation_plans') or []):
        issues = [row for row in issues_by_plan.get(index, []) if row.get('severity') == 'blocking']
        for issue in issues:
            code = issue.get('code')
            text_fields = {
                'internal_link_direction': ('simple_explanation', 'technical_explanation', 'rationale', 'implementation_steps'),
                'unproven_necessity': ('rationale', 'technical_explanation'),
                'generic_non_actionable_plan': ('implementation_steps',),
                'unsupported_causal_ranking_claim': ('technical_explanation', 'rationale', 'implementation_steps'),
                'unsupported_quality_inference': ('simple_explanation', 'technical_explanation', 'rationale'),
                'unmeasured_user_loss': ('simple_explanation',),
            }.get(code, tuple(plan))
            original_fields = {field: plan.get(field) for field in text_fields if field in plan}
            blocker_audit.append({'plan_index': index, 'plan_title': plan.get('title'),
                'finding_ids': plan.get('specialist_finding_ids', []),
                'evidence_ids': plan.get('evidence_ids', []),
                'invalid_statement_or_scope': issue.get('message'),
                'original_invalid_field_values': original_fields,
                'original_plan': plan,
                'issue_code': issue.get('code'), 'path': issue.get('path'),
                'original_plan_preserved': True,
                'user_facing_status': 'withheld_from_authoritative_actions',
                'safe_recovery': 'No paraphrase or unsupported substitute was emitted. Existing deterministic recommendation remains available when supported by the same evidence; the original specialist plan and finding stay in the technical appendix/audit.'})
    save(out / 'validation_recovery_blocker_trace.json', {
        'saved_specialist_quality_flags': {'blocking': quality.get('blocking_count'), 'review': quality.get('review_count')},
        'blocking_findings': blocker_audit,
        'all_original_findings_preserved': json.loads((out / 'offline/llm_outputs/information_preservation_report.json').read_text(encoding='utf-8'))['all_original_findings_preserved'],
        'unsupported_plans_user_facing': False,
    })

    canonical = json.loads((project / 'output/results/aviator/llm_foundation/canonical_evidence.json').read_text(encoding='utf-8'))
    from hashlib import sha256
    canonical['_source_sha256'] = sha256((project / 'output/results/aviator/llm_foundation/canonical_evidence.json').read_bytes()).hexdigest()
    serp = json.loads((project / 'data/processed/aviator/serp_google.json').read_text(encoding='utf-8'))
    rec_manifest = json.loads((out / 'offline/offline_run_manifest.json').read_text(encoding='utf-8'))
    pdf = out / 'aviator_draft_management_report.pdf'
    appendix = out / 'aviator_technical_appendix.md'
    build_management_pdf(pdf, data, specialist, quality, 'aviator', canonical, serp.get('datetime'))
    run_records = json.loads((out / 'offline/validation_and_recovery_audit.json').read_text(encoding='utf-8')).get('task_records')
    appendix_text = build_appendix(data, specialist, quality, comparison_path.name, canonical, run_records)
    appendix_text += '\n## Task 5 specialist blocker recovery trace\n\n```json\n'
    appendix_text += json.dumps(blocker_audit, ensure_ascii=False, indent=2) + '\n```\n'
    appendix_text += '\n## Task 5 recommendation reconciliation audit\n\n```json\n'
    appendix_text += json.dumps(reconciliation, ensure_ascii=False, indent=2) + '\n```\n'
    appendix.write_text(appendix_text, encoding='utf-8')
    save(out / 'aviator_recommendations.json', data)

    from analysis.recommendation_classification import TIER_ORDER
    tiers = TIER_ORDER
    rec_rows = [{'order': row.get('order'), 'id': row.get('id'), 'title': row.get('title'),
        'tier': row.get('evidence_tier'), 'priority_score': row.get('priority_score'),
        'display_action': row.get('display_action'), 'full_actions': row.get('actions'),
        'evidence_provenance': row.get('evidence_provenance')} for row in authoritative]
    classification = {'recommendations': rec_rows,
        'tier_counts': {tier: sum(row.get('evidence_tier') == tier for row in authoritative) for tier in tiers},
        'ordered_by_tier_and_priority': [(tiers.get(row.get('evidence_tier'), 99), -float(row.get('priority_score') or 0))
            for row in authoritative] == sorted((tiers.get(row.get('evidence_tier'), 99),
            -float(row.get('priority_score') or 0)) for row in authoritative),
        'no_other_tiers': all(row.get('evidence_tier') in tiers for row in authoritative)}
    save(out / 'evidence_tier_classification.json', classification)
    synthetic = json.loads((out / 'offline/synthetic_keyword_results.json').read_text(encoding='utf-8'))
    save(out / 'synthetic_keyword_results.json', synthetic)

    before_by_id = {row.get('id'): row for row in previous_task4_recommendations}
    comparisons = []
    for row in authoritative:
        previous = before_by_id.get(row.get('id')) or (
            before_by_id.get('technical-mobile') if row.get('id', '').startswith('technical-mobile-') else None)
        comparisons.append({'id': row.get('id'), 'title': row.get('title'),
            'before': {'action': previous.get('actions'), 'tier': previous.get('evidence_tier')} if previous else None,
            'after': {'display_action': row.get('display_action'), 'full_action': row.get('actions'),
                      'tier': row.get('evidence_tier')},
            'assessment': ('More usable to scan: the bundled Lighthouse action is split into a diagnostic-specific card, while exact resources and implementation steps remain in the appendix. Evidence and proposed change are materially the same.' if row.get('id', '').startswith('technical-mobile-') else
                'Retained from the saved Task 4 set. No material change in evidence or proposed action.' if previous else
                'New separate diagnostic action derived from a verified resource-level Lighthouse observation.')})
    criterion_scores = [
        {'criterion': 'Sensibility', 'task4': 4, 'task5': 4,
         'reason': 'The same evidence and uncertainty qualifiers are retained; Task 5 adds no ranking-causality claims.'},
        {'criterion': 'Descriptiveness', 'task4': 4, 'task5': 4,
         'reason': 'Technical recommendations are separated by Lighthouse issue; precise resources and implementation steps remain in the appendix.'},
        {'criterion': 'Actionability', 'task4': 4, 'task5': 4,
         'reason': 'Existing query pages, source/destination URLs and safe implementation steps are retained; technical actions have focused cards.'},
        {'criterion': 'Evidence accuracy', 'task4': 4, 'task5': 4,
         'reason': 'No new factual claim is introduced; specialist plans with quality findings remain withheld and traceable.'},
        {'criterion': 'Technical usefulness', 'task4': 4, 'task5': 4,
         'reason': 'Lighthouse issues are split and safeguards retained; no unimplemented optimization is represented as measured.'},
        {'criterion': 'Coverage', 'task4': 4, 'task5': 4,
         'reason': 'The supported opportunity areas remain covered. No unsupported backlink, FAQ or content-gap claim is added.'},
    ]
    reference_report = json.loads((project / 'output/task4_evaluation/aviator/quality_evaluation_report.json').read_text(encoding='utf-8'))
    report = {'title': 'Task 5 — Precision, Validation and Reporting Integration',
        'mode': 'saved evidence and saved specialist responses; external requests = 0',
        'before_after_recommendations': comparisons,
        'recommendation_count_before': len(previous_task4_recommendations),
        'recommendation_count_current_pipeline_before_reconciliation': len(original_recommendations),
        'recommendation_count_after': len(authoritative),
        'quality_scores_1_to_5': criterion_scores,
        'quality_score_interpretation': 'Comparative rubric judgments, not measured outcomes; Task 5 improves technical card separation but does not claim an overall quality-score increase.',
        'benchmark_comparison': {
            'resolved_references': reference_report.get('reference_files_resolved', []),
            'previous_management_report': 'development_references/aviator_executive_report (1).pdf',
            'reference_traceability': 'Task 4 benchmark review carried forward; legacy word-count, link-count and backlink observations are historical context, not current evidence.',
            'supported_gaps_addressed': reference_report.get('comparison', {}).get('historical_reference_gaps_addressed', []),
            'reference_limitations': reference_report.get('comparison', {}).get('reference_limitations_retained', []),
        },
        'tier_counts': classification['tier_counts'],
        'reconciliation': reconciliation,
        'specialist_quality_flags': {'blocking': quality.get('blocking_count'), 'review': quality.get('review_count')},
        'source_preservation': json.loads((out / 'offline/validation_and_recovery_audit.json').read_text(encoding='utf-8'))['source_inputs_unchanged'],
        'synthetic_keyword_checks': synthetic,
        'known_limitations': ['Saved Gemma specialist plans have blocker/review findings and are withheld from the action list; no live requests were made to attempt repairs.',
            'Current page-pair evidence lacks content captures for several query-mapped pages, so additions remain conditional and no specific missing section is asserted.',
            'No historical controlled outcome evidence is available for Tier 1.']}
    save(out / 'final_evaluation_report.json', report)
    eval_md = ['# Task 5 final evaluation', '',
        'Offline saved-evidence run; zero external requests. Original investigation and saved specialist inputs were preserved.', '',
        f"Recommendation count: {len(previous_task4_recommendations)} in the saved Task 4 baseline; {len(authoritative)} after Task 5 reconciliation.",
        f"Evidence tiers: {classification['tier_counts']}.", '',
        '## Comparative quality rubric (1–5)', '',
        '| Criterion | Task 4 | Task 5 | Assessment |', '|---|---:|---:|---|']
    eval_md.extend(f"| {row['criterion']} | {row['task4']} | {row['task5']} | {row['reason']} |" for row in criterion_scores)
    eval_md.extend(['', '## Benchmark comparison', '',
        'Resolved references: `development_references/OUTPUTSERP 1 1.txt` and `development_references/aviator_executive_report (1).pdf`. Historical benchmark observations were treated as context, not current page evidence.', '',
        '| Recommendation | Before/after assessment |', '|---|---|'])
    eval_md.extend(f"| {row['title']} | {row['assessment']} |" for row in comparisons)
    eval_md.extend(['', '## Remaining limits', ''] + [f"- {item}" for item in report['known_limitations']])
    (out / 'final_evaluation_report.md').write_text('\n'.join(eval_md) + '\n', encoding='utf-8')
    from datetime import datetime, timezone
    save(out / 'offline_run_manifest.json', {'mode': 'task5_saved_evidence_offline', 'external_requests': 0,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'recommendations_json': str((out / 'aviator_recommendations.json').resolve()),
        'management_pdf': str(pdf.resolve()), 'technical_appendix': str(appendix.resolve()),
        'classification': str((out / 'evidence_tier_classification.json').resolve()),
        'validation_recovery_audit': str((out / 'validation_recovery_blocker_trace.json').resolve()),
        'evaluation_report': str((out / 'final_evaluation_report.json').resolve()),
        'draft_not_approved_or_published': True,
        'source_inputs_unchanged': report['source_preservation'],
        'previous_task4_manifest': rec_manifest})
    print(json.dumps({'output_dir': str(out), 'external_requests': 0,
        'recommendation_count': len(authoritative), 'tier_counts': classification['tier_counts'],
        'blockers': quality.get('blocking_count'), 'review_flags': quality.get('review_count'),
        'source_inputs_unchanged': report['source_preservation']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
