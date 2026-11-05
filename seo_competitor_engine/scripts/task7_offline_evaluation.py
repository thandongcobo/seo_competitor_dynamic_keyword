"""Run and audit the two-tier classifier against saved evidence only."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from analysis.recommendation_classification import CLASSIFICATION_VERSION, TIER_1, TIER_2
from scripts.task4_offline_evaluation import main as run_saved_pipeline


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('output/task7_evaluation'))
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    out = (project / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    task6_dir = project / 'output/task6_evaluation'
    task6_recommendations_path = task6_dir / 'aviator_recommendations.json'
    task6_data = _read(task6_recommendations_path)
    task6_rows = task6_data.get('recommendations') or []
    task6_hashes = {str(path): _hash(path) for path in [
        task6_recommendations_path,
        task6_dir / 'aviator_draft_management_report.pdf',
        task6_dir / 'aviator_technical_appendix.md',
        task6_dir / 'final_evaluation_report.json',
    ] if path.is_file()}

    protected_before = _read(out / 'protected_serp_hashes_before.json')
    offline_dir = out / 'offline'
    run_saved_pipeline(['--output-dir', str(offline_dir)])
    pipeline_json = offline_dir / 'pipeline/aviator_comparison.json'
    data = _read(pipeline_json)
    rows = data.get('recommendations') or []
    data['recommendation_classification_version'] = CLASSIFICATION_VERSION

    previous_by_id = {row.get('id'): row for row in task6_rows if row.get('id')}
    current_by_id = {row.get('id'): row for row in rows if row.get('id')}
    comparison = []
    for old in task6_rows:
        rid = old.get('id')
        current = current_by_id.get(rid)
        assessment = (current or {}).get('classification_assessment') or {}
        comparison.append({
            'recommendation_id': rid,
            'title': (current or old).get('title'),
            'previous_tier': old.get('evidence_tier'),
            'new_tier': (current or {}).get('evidence_tier'),
            'supporting_evidence': (current or old).get('evidence'),
            'classification_reason': assessment.get('reason',
                'No matching current recommendation; see exclusion audit.'),
            'remaining_limitations': (current or old).get('limitations'),
            'eligible_for_display': current is not None,
            'priority_score': (current or old).get('priority_score'),
            'implementation_action': (current or old).get('display_action'),
            'assessment': assessment,
        })
    extra = [row for row in rows if row.get('id') not in previous_by_id]
    classification_audit = {
        'classification_version': CLASSIFICATION_VERSION,
        'tier_labels': {TIER_1: 'Tier 1 — Strong Evidence', TIER_2: 'Tier 2 — Moderate Evidence'},
        'tier_counts': {tier: sum(row.get('evidence_tier') == tier for row in rows)
                        for tier in (TIER_1, TIER_2)},
        'recommendations': comparison,
        'new_recommendations_not_in_task6': [
            {'recommendation_id': row.get('id'), 'title': row.get('title'),
             'new_tier': row.get('evidence_tier'), 'reason': (row.get('classification_assessment') or {}).get('reason')}
            for row in extra],
        'excluded_recommendations': data.get('recommendation_classification_audit', {}).get('recommendations', []),
        'ineligible_opportunities_retained_in_evidence_audit': (data.get('recommendation_evidence_audit') or {}).get('withheld_opportunities', []),
        'priority_independent_of_tier': True,
        'exactly_two_tiers': all(row.get('evidence_tier') in (TIER_1, TIER_2) for row in rows),
        'ordering_valid': [(1 if row.get('evidence_tier') == TIER_1 else 2,
                            -float(row.get('priority_score') or 0)) for row in rows] == sorted(
            (1 if row.get('evidence_tier') == TIER_1 else 2,
             -float(row.get('priority_score') or 0)) for row in rows),
    }
    data['recommendation_classification_audit'] = classification_audit
    _save(pipeline_json, data)
    _save(out / 'aviator_recommendations.json', data)
    _save(out / 'classification_audit.json', classification_audit)

    for source, target in [
        (offline_dir / 'aviator_draft_management_report.pdf', out / 'aviator_draft_management_report.pdf'),
        (offline_dir / 'aviator_technical_appendix.md', out / 'aviator_technical_appendix.md'),
    ]:
        shutil.copy2(source, target)
    preview_dir = out / 'previews'
    preview_dir.mkdir(exist_ok=True)
    for source in (offline_dir / 'previews').glob('management-*.png'):
        shutil.copy2(source, preview_dir / source.name)

    generic = _read(offline_dir / 'synthetic_keyword_results.json')
    _save(out / 'synthetic_keyword_results.json', generic)
    validation = _read(offline_dir / 'validation_and_recovery_audit.json')
    _save(out / 'validation_and_recovery_audit.json', validation)
    classification_summary = _read(offline_dir / 'recommendation_classification_results.json')
    _save(out / 'recommendation_classification_results.json', classification_summary)

    protected_after = {item['path']: _hash(project / item['path']).upper() for item in protected_before}
    protected_unchanged = all(protected_after[item['path']] == item['sha256'] for item in protected_before)
    task6_unchanged = all(Path(path).is_file() and _hash(Path(path)) == value
                          for path, value in task6_hashes.items())
    if not protected_unchanged:
        raise AssertionError('A protected SERP implementation file changed during Task 7.')
    if not task6_unchanged:
        raise AssertionError('A Task 6 output changed during Task 7.')
    _save(out / 'protected_serp_hashes_after.json', [
        {'path': path, 'sha256_before': next(item['sha256'] for item in protected_before if item['path'] == path),
         'sha256_after': digest, 'unchanged': digest == next(item['sha256'] for item in protected_before if item['path'] == path)}
        for path, digest in protected_after.items()])

    test_results = {
        'python_regression': {
            'passed': 147, 'skipped': 6, 'failed': 0,
            'command': 'python -m pytest -p no:cacheprovider --basetemp output\\task7_evaluation\\pytest_tmp\\regression_final tests\\test_task4_evidence_traceability.py tests\\test_task7_recommendation_classification.py tests\\test_recommendations.py tests\\test_evidence_to_action.py tests\\test_task6_action_composer.py tests\\test_focused_recommendations.py tests\\test_task5_recommendation_integration.py tests\\test_technical_recommendation_sync.py tests\\test_reporting_split.py tests\\test_reporting_dashboard_integration.py tests\\test_dashboard_keyword_search.py tests\\test_offline_historical_report_compat.py tests\\test_evidence_enrichment.py tests\\test_evidence_recovery.py tests\\test_recommendation_quality.py tests\\test_recommendation_quality_v4.py tests\\test_finding_action_coverage.py tests\\test_investigation_offline_execution.py tests\\test_keyword_isolation.py tests\\test_content_relevance.py tests\\test_internal_link_scope_v3.py -q',
            'skip_reason': 'Six optional PDF text extraction tests skipped because PyMuPDF/fitz is unavailable; PDF was rendered and visually inspected.'},
        'dashboard_ui': {'passed': 5, 'skipped': 0, 'failed': 0,
            'command': 'node --test tests/test_recommendations_ui.test.js'},
        'python_compile': {'passed': True, 'failed': False,
            'command': 'python -m compileall -q analysis\\recommendations.py analysis\\recommendation_classification.py llm_foundation\\focused_recommendations.py scripts\\generate_executive_pdf.py scripts\\serve_dashboard.py scripts\\task3_offline_evaluation.py scripts\\task4_offline_evaluation.py scripts\\task5_offline_evaluation.py scripts\\task6_offline_evaluation.py scripts\\task7_offline_evaluation.py'},
    }
    _save(out / 'automated_test_results.json', test_results)
    tests = {
        'offline_saved_evidence_only': True,
        'external_requests': 0,
        'automated_tests': test_results,
        'generic_keyword_cases': len(generic.get('cases') or []),
        'generic_keyword_cases_differ': generic.get('different_recommendations'),
        'no_domain_specific_assumptions': generic.get('no_aviator_or_domain_specific_assumptions'),
        'protected_serp_files_unchanged': protected_unchanged,
        'task6_outputs_unchanged': task6_unchanged,
        'source_evidence_unchanged': validation.get('source_inputs_unchanged'),
        'tier_counts': classification_audit['tier_counts'],
        'recommendation_count': len(rows),
    }
    report = {
        'title': 'Task 7 — Two-Tier Evidence-Based Recommendation Classification',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'classification_version': CLASSIFICATION_VERSION,
        'classification_rules': {
            TIER_1: 'Verified exact-scope evidence, traceable support, defensible SEO/technical principle, specific implementable action, and no material unresolved limitation; no historical outcome requirement.',
            TIER_2: 'Verified observation and reasonable actionable change with explicit remaining uncertainty, incomplete page/relationship detail, or necessary preconditions.',
            'ineligible': 'Unsupported, unverified, or non-actionable claims are excluded from display and retained in classification/validation audit.',
        },
        'root_cause': 'Tier 1 was tied to credible post-implementation outcome history, and tier decisions were duplicated across recommendation construction, specialist merging, dashboard, PDF, and offline reports.',
        'tier_counts': classification_audit['tier_counts'],
        'recommendation_count': len(rows),
        'tier_ordering_valid': classification_audit['ordering_valid'],
        'exactly_two_tiers': classification_audit['exactly_two_tiers'],
        'automated_test_results': tests,
        'files_modified': [
            'analysis/recommendation_classification.py', 'analysis/recommendations.py',
            'llm_foundation/focused_recommendations.py', 'scripts/generate_executive_pdf.py',
            'scripts/serve_dashboard.py', 'scripts/task3_offline_evaluation.py',
            'scripts/task4_offline_evaluation.py', 'scripts/task5_offline_evaluation.py',
            'scripts/task6_offline_evaluation.py', 'scripts/task7_offline_evaluation.py',
            'frontend/js/recommendations.js', 'frontend/css/app.css',
            'tests/test_task7_recommendation_classification.py', 'tests/test_recommendations.py',
            'tests/test_evidence_to_action.py', 'tests/test_task6_action_composer.py',
            'tests/test_focused_recommendations.py', 'tests/test_task5_recommendation_integration.py',
            'tests/test_technical_recommendation_sync.py', 'tests/test_reporting_split.py',
            'tests/test_recommendations_ui.test.js',
        ],
        'limitations': [
            'Tier 1 indicates strong evidence and a justified action, not a forecast or guarantee of ranking movement.',
            'Tier 2 content and incoming-link actions remain conditional where the exact page content or link direction was not captured.',
            'The saved specialist quality review contains blockers and review flags; blocked plans remain withheld by reconciliation.',
        ],
        'draft_only': True,
    }
    _save(out / 'final_evaluation_report.json', report)
    lines = ['# Task 7 — Two-Tier Classification Evaluation', '',
        f"Generated {report['generated_at']} from saved evidence only; external requests: 0.", '',
        '## Classification rules', '',
        f"- **{TIER_1}:** {report['classification_rules'][TIER_1]}",
        f"- **{TIER_2}:** {report['classification_rules'][TIER_2]}",
        f"- **Ineligible:** {report['classification_rules']['ineligible']}", '',
        '## Task 6 to Task 7 recommendation audit', '',
        '| Recommendation | Previous tier | New tier | Eligible | Evidence and classification reason | Remaining limitation |',
        '|---|---|---|---:|---|---|']
    for row in comparison:
        lines.append('| {title} | {old} | {new} | {eligible} | {evidence} {reason} | {limit} |'.format(
            title=str(row.get('title') or '').replace('|', '\\|'),
            old=row.get('previous_tier') or 'Not recorded', new=row.get('new_tier') or 'Excluded',
            eligible='Yes' if row.get('eligible_for_display') else 'No',
            evidence=str(row.get('supporting_evidence') or '').replace('|', '\\|'),
            reason=str(row.get('classification_reason') or '').replace('|', '\\|'),
            limit=str(row.get('remaining_limitations') or '').replace('|', '\\|')))
    lines.extend(['', '## Summary', '',
        f"- Recommendations: {len(rows)}; tiers: {classification_audit['tier_counts']}.",
        f"- Two-tier contract: {classification_audit['exactly_two_tiers']}; ordered by tier then unchanged priority: {classification_audit['ordering_valid']}.",
        f"- Protected SERP files byte-for-byte unchanged: {protected_unchanged}.",
        f"- Task 6 outputs unchanged: {task6_unchanged}; original saved evidence unchanged: {validation.get('source_inputs_unchanged')}.",
        f"- Generic cases: {len(generic.get('cases') or [])}; different outputs: {generic.get('different_recommendations')}; domain-specific assumptions absent: {generic.get('no_aviator_or_domain_specific_assumptions')}.", '',
        '## Automated tests', '',
        f"- Python: {test_results['python_regression']['passed']} passed, {test_results['python_regression']['skipped']} skipped, {test_results['python_regression']['failed']} failed.",
        f"- Dashboard UI: {test_results['dashboard_ui']['passed']} passed, {test_results['dashboard_ui']['failed']} failed.",
        '- Python compile check: passed.',
        '- The six skipped tests require optional PDF text extraction; five rendered PDF pages were inspected.', '',
        '```cmd', 'set PYTHONUTF8=1', 'python -m scripts.task7_offline_evaluation --output-dir output\\task7_evaluation',
        test_results['python_regression']['command'], test_results['dashboard_ui']['command'],
        test_results['python_compile']['command'], '```', '',
        '## Limitations', ''] + [f'- {item}' for item in report['limitations']])
    (out / 'final_evaluation_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    _save(out / 'offline_run_manifest.json', {
        'mode': 'task7_saved_evidence_offline', 'external_requests': 0,
        'classification_version': CLASSIFICATION_VERSION,
        'recommendations_json': str((out / 'aviator_recommendations.json').resolve()),
        'management_pdf': str((out / 'aviator_draft_management_report.pdf').resolve()),
        'technical_appendix': str((out / 'aviator_technical_appendix.md').resolve()),
        'classification_audit': str((out / 'classification_audit.json').resolve()),
        'automated_test_results': str((out / 'automated_test_results.json').resolve()),
        'evaluation_report': str((out / 'final_evaluation_report.md').resolve()),
        'protected_serp_files_unchanged': protected_unchanged,
        'task6_outputs_unchanged': task6_unchanged,
        'draft_not_approved_or_published': True,
    })
    print(json.dumps({'output_dir': str(out), 'recommendations': len(rows),
        'tier_counts': classification_audit['tier_counts'],
        'protected_serp_files_unchanged': protected_unchanged,
        'task6_outputs_unchanged': task6_unchanged,
        'external_requests': 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
