"""Offline Task 4 evidence-to-action evaluation using saved investigation data only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from analysis.recommendations import (
    build_recommendation_evidence_audit,
    classify_evidence_tier,
    generate_recommendations,
)
from llm_foundation.enrichment import enrich_comparison
from llm_foundation.executive_synthesis import build_packet
from llm_foundation.evidence_recovery import recover_invalid_task
from llm_foundation.focused_recommendations import TASKS, merge_tasks, task_packet, validate_task
from llm_foundation.recommendation_quality import audit_recommendations
from scripts.generate_executive_pdf import build_appendix, build_management_pdf
from scripts.run_llm_focused_recommendations import load_saved, save_preservation_report


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('output/task4_evaluation/aviator'))
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    out = (project / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    # All required evidence and specialist responses are local saved files.
    pipeline_out = out / 'pipeline'
    from scripts.run_analysis import main as run_saved_analysis
    run_saved_analysis(pipeline_out)
    comparison_path = pipeline_out / 'aviator_comparison.json'
    data = json.loads(comparison_path.read_text(encoding='utf-8'))
    enrichment = enrich_comparison(data, comparison_path,
        raw_data_root=project / 'data/raw')
    data['recommendations'] = generate_recommendations(
        keyword=data['keyword'], ranking_urls=data['primary_ranking_urls'],
        advanced_evidence=data.get('advanced_evidence') or {},
        onpage=data.get('onpage_comparison') or {},
        technical_comparison=data.get('technical_comparison') or {},
        enriched_page_evidence=enrichment.get('onpage'),
    )
    data['recommendation_evidence_audit'] = build_recommendation_evidence_audit(
        keyword=data['keyword'], ranking_urls=data['primary_ranking_urls'],
        advanced_evidence=data.get('advanced_evidence') or {},
        enriched_page_evidence=enrichment.get('onpage'))
    data['recommendation_classification_version'] = 2
    save(comparison_path, data)

    saved_root = project / 'output/results/aviator'
    packet, specialists = load_saved(saved_root)
    original_paths = [saved_root / 'aviator_comparison.json',
                      saved_root / 'llm_foundation/canonical_evidence.json']
    original_paths.extend(saved_root / 'llm_outputs' / f'{task}_validated.json' for task in TASKS)
    focused_cache = project / 'output/gemma_tests/aviator/focused/llm_outputs/focused_tasks'
    original_paths.extend(path for path in focused_cache.glob('*') if path.is_file())
    original_hashes = {str(path): digest(path) for path in original_paths if path.is_file()}

    focused_outputs, records = {}, []
    for task in TASKS:
        source = focused_cache / f'{task}_validated.json'
        saved = json.loads(source.read_text(encoding='utf-8'))
        response = saved['result']
        scoped = task_packet(packet, task)
        errors = validate_task(response, scoped, task)
        recovery = None
        if errors:
            response, recovery = recover_invalid_task(response, errors, scoped, task)
            if response is None:
                raise ValueError(f'{task}: saved response cannot be safely recovered: {errors}')
            remaining = validate_task(response, scoped, task)
            if remaining:
                raise ValueError(f'{task}: response still invalid after recovery: {remaining}')
        focused_outputs[task] = response
        records.append({'task': task,
                        'status': 'recovered_with_review' if recovery else 'validated_saved_response',
                        'attempts': saved.get('attempts'),
                        'recovery_status': recovery.get('status') if recovery else 'not_triggered',
                        'review_finding_ids': recovery.get('review_finding_ids', []) if recovery else [],
                        'recovery_audit': recovery})

    merged = merge_tasks(packet, focused_outputs)
    quality = audit_recommendations(merged,
        expected_findings=[row['id'] for row in packet['specialist_findings']],
        require_actionable=True, enforce_causation=True, enforce_unmeasured_loss=True)
    save(out / 'saved_inputs/executive_validated_rechecked.json', merged)
    save(out / 'saved_inputs/recommendation_quality_report.json', quality)
    (out / 'llm_outputs').mkdir(exist_ok=True)
    save(out / 'llm_outputs/executive_validated.json', merged)
    save(out / 'llm_outputs/recommendation_quality_report.json', quality)
    preservation = save_preservation_report(out, specialists, merged)
    canonical_path = saved_root / 'llm_foundation/canonical_evidence.json'
    canonical = json.loads(canonical_path.read_text(encoding='utf-8'))
    canonical['_source_sha256'] = digest(canonical_path)

    from analysis.recommendation_classification import TIER_1, TIER_2, adapt_recommendations
    tiers = [TIER_1, TIER_2]
    recommendations = data['recommendations']
    focused_classified, focused_classification_audit = adapt_recommendations(
        merged.get('implementation_plans', []))
    classification = {
        'classification_version': 2,
        'keyword': data['keyword'],
        'deterministic_recommendations': [
            {'order': row['order'], 'id': row['id'], 'title': row['title'],
             'tier': row['evidence_tier'], 'priority_score': row['priority_score'],
             'difference_observed': row['evidence'], 'potential_impact': row['interpretation'],
             'recommended_action': row['actions'], 'evidence_provenance': row['evidence_provenance']}
            for row in recommendations],
        'tier_counts': {tier: sum(row['evidence_tier'] == tier for row in recommendations) for tier in tiers},
        'ordering_valid': [row['evidence_tier'] for row in recommendations] == sorted(
            (row['evidence_tier'] for row in recommendations), key=tiers.index),
        'tier_rule_checks': {
            'verified_specific_action_tier_1_without_history': classify_evidence_tier(
                observation_verified=True, action_supported=True, established_principle=True,
                exact_scope_verified=True, action_specific=True) == TIER_1,
            'numerical_observation_alone_not_tier_1': classify_evidence_tier(
                observation_verified=True, action_supported=True, established_principle=False,
                exact_scope_verified=True, action_specific=True) is None,
            'moderate_uncertainty_remains_tier_2': classify_evidence_tier(
                observation_verified=True, action_supported=True, established_principle=True,
                exact_scope_verified=False, action_specific=True,
                material_uncertainty=True) == TIER_2,
            'unsupported_observation_ineligible': classify_evidence_tier(
                observation_verified=False, action_supported=True) is None,
        },
        'focused_saved_plan_tiers': [{'title': plan['title'], 'tier': plan['evidence_tier'],
             'evidence_ids': plan.get('evidence_ids', []),
             'specialist_finding_ids': plan.get('specialist_finding_ids', [])}
             for plan in focused_classified],
        'focused_tier_counts': {tier: sum(plan['evidence_tier'] == tier
                                          for plan in focused_classified) for tier in tiers},
        'focused_plan_classification_audit': focused_classification_audit,
    }
    save(out / 'recommendation_classification_results.json', classification)
    synthetic_cases = [
        {'keyword': 'residential solar inverter',
         'urls': {'ours': 'https://example.org/guides/solar-inverters',
                  'benchmark': 'https://other.example/reviews/inverters'},
         'onpage': {'title_keyword_match': {'ours': False, 'competitor': True}},
         'expected_id': 'onpage-title_keyword_match'},
        {'keyword': 'home compost bin odor control',
         'urls': {'ours': 'https://green.example/guides/compost-bin',
                  'benchmark': 'https://earth.example/composting/odor'},
         'onpage': {'meta_keyword_match': {'ours': False, 'competitor': True}},
         'expected_id': 'onpage-meta_keyword_match'},
    ]
    synthetic_results = []
    for case in synthetic_cases:
        rows = generate_recommendations(keyword=case['keyword'], ranking_urls=case['urls'],
            advanced_evidence={}, onpage=case['onpage'])
        synthetic_results.append({'keyword': case['keyword'], 'urls': case['urls'],
            'recommendation_ids': [row['id'] for row in rows],
            'tiers': [row['evidence_tier'] for row in rows],
            'expected_recommendation_present': case['expected_id'] in {row['id'] for row in rows}})
    synthetic_eval = {'offline': True, 'external_requests': 0, 'cases': synthetic_results,
        'no_aviator_or_domain_specific_assumptions': all(
            'aviator' not in json.dumps(row).lower() and
            'hollywoodbets' not in json.dumps(row).lower() for row in synthetic_results),
        'different_recommendations': synthetic_results[0]['recommendation_ids'] != synthetic_results[1]['recommendation_ids']}
    save(out / 'synthetic_keyword_results.json', synthetic_eval)
    validation = {
        'offline_only': True, 'external_requests': 0, 'saved_specialist_responses_revalidated': True,
        'task_records': records, 'quality_audit': quality,
        'information_preservation': preservation,
        'synthetic_keyword_tests': synthetic_eval,
        'original_input_sha256': original_hashes,
        'source_inputs_unchanged': all(digest(Path(path)) == value for path, value in original_hashes.items()),
        'withheld_opportunities': data.get('recommendation_evidence_audit', {}).get('withheld_opportunities', []),
        'note': 'Saved specialist responses were revalidated locally. Current recommendations use two evidence tiers; Tier 1 reflects verified exact-scope evidence and a specific supported action, without requiring historical outcomes.',
    }
    save(out / 'validation_and_recovery_audit.json', validation)
    serp = json.loads((project / 'data/processed/aviator/serp_google.json').read_text(encoding='utf-8'))
    pdf = out / 'aviator_draft_management_report.pdf'
    appendix_path = out / 'aviator_technical_appendix.md'
    build_management_pdf(pdf, data, merged, quality, 'aviator', canonical, serp.get('datetime'))
    appendix = build_appendix(data, merged, quality, comparison_path.name, canonical, records)
    appendix += '\n## Task 4 deterministic recommendation evidence audit\n\n```json\n'
    appendix += json.dumps(data.get('recommendation_evidence_audit', {}), ensure_ascii=False, indent=2)
    appendix += '\n```\n'
    appendix_path.write_text(appendix, encoding='utf-8')

    manifest = {'mode': 'saved_evidence_offline_task4', 'external_requests': 0,
        'recommendation_json': str(comparison_path), 'management_pdf': str(pdf),
        'technical_appendix': str(appendix_path),
        'classification_results': str(out / 'recommendation_classification_results.json'),
        'validation_recovery_audit': str(out / 'validation_and_recovery_audit.json'),
        'deterministic_recommendation_count': len(recommendations),
        'focused_saved_implementation_plan_count': len(merged.get('implementation_plans', [])),
        'source_inputs_unchanged': validation['source_inputs_unchanged'],
        'draft_status': 'not approved or published'}
    save(out / 'offline_run_manifest.json', manifest)
    if not validation['source_inputs_unchanged']:
        raise AssertionError('A saved source input changed during offline evaluation.')
    import subprocess
    preview_dir = out / 'previews'
    preview_dir.mkdir(exist_ok=True)
    preview_prefix = preview_dir / 'management'
    subprocess.run(['pdftoppm', '-png', '-r', '100', str(pdf), str(preview_prefix)],
                   check=True, capture_output=True)
    previews = sorted(preview_dir.glob('management-*.png'))
    print(json.dumps({'output_dir': str(out), 'external_requests': 0,
        'recommendation_count': len(recommendations), 'tier_counts': classification['tier_counts'],
        'focused_tier_counts': classification['focused_tier_counts'],
        'quality_blocking_flags': quality.get('blocking_count'),
        'quality_review_flags': quality.get('review_count'),
        'source_inputs_unchanged': validation['source_inputs_unchanged'],
        'pdf_preview_pages': [str(path) for path in previews]}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

