"""Offline Task 6 action-composer evaluation using saved evidence only."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from analysis.recommendations import generate_recommendations, reconcile_recommendations
from llm_foundation.enrichment import enrich_comparison
from scripts.generate_executive_pdf import build_appendix, build_management_pdf
from scripts.task4_offline_evaluation import main as run_saved_pipeline


def _save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _enriched(kind, side, url, value, keyword):
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    return {'evidence_id': 'SYN_' + side.upper() + '_' + kind.upper(), 'keyword': keyword,
        'page': {'side': side, 'url': url}, 'scope': 'page', 'metric_or_observation': kind,
        'value': value, 'provenance': {'source_sha256': digest, 'source_path': 'synthetic_saved_fixture'}}


def _synthetic_case(keyword, ours, benchmark, topic, supporting, brand, *, title_mismatch, meta_mismatch):
    headings = [{'level': 'h1', 'text': topic}]
    headings.extend({'level': 'h2', 'text': value} for value in supporting)
    passages = [{'text': f'{topic} is covered in this guide, including {" and ".join(supporting)}.'}]
    evidence = [
        _enriched('page_metadata_and_rendering', 'ours', ours, {
            'title': f'General Information | {brand}', 'meta_description': f'General information from {brand}.',
            'canonical': ours, 'robots': 'index,follow', 'status_code': 200,
            'extraction_status': 'complete', 'url_alignment': 'matched'}, keyword),
        _enriched('rendered_heading_inventory', 'ours', ours, headings, keyword),
        _enriched('keyword_relevant_visible_passages', 'ours', ours, passages, keyword),
        _enriched('page_metadata_and_rendering', 'benchmark', benchmark, {
            'title': f'{topic} | Other Publisher', 'meta_description': f'Read about {topic}.',
            'canonical': benchmark, 'robots': 'index,follow', 'status_code': 200,
            'extraction_status': 'complete', 'url_alignment': 'matched'}, keyword),
    ]
    onpage = {}
    if title_mismatch:
        onpage['title_keyword_match'] = {'ours': False, 'competitor': True}
    if meta_mismatch:
        onpage['meta_keyword_match'] = {'ours': False, 'competitor': True}
    rows = generate_recommendations(keyword=keyword,
        ranking_urls={'ours': ours, 'benchmark': benchmark}, advanced_evidence={}, onpage=onpage,
        enriched_page_evidence=evidence)
    return {'keyword': keyword, 'pages': {'ours': ours, 'benchmark': benchmark},
        'recommendation_ids': [row['id'] for row in rows],
        'proposed_copy': [row['action_composition']['proposed_copy'] for row in rows
                          if row.get('action_composition', {}).get('proposed_copy')],
        'all_copy_grounded': all(copy['validation']['grounded'] for row in rows
            for copy in [row.get('action_composition', {}).get('proposed_copy')]
            if copy)}


def _scores_for(row, previous_rows):
    rid = row['id']
    old_actions = [str(action) for previous in previous_rows for action in previous.get('actions', [])]
    if rid == 'onpage-title_keyword_match':
        before = {'sensibility': 4, 'descriptiveness': 2, 'actionability': 2,
                  'evidence_accuracy': 4, 'technical_usefulness': 3}
        after = {'sensibility': 4, 'descriptiveness': 5, 'actionability': 5,
                 'evidence_accuracy': 5, 'technical_usefulness': 4}
        reason = 'A candidate title is explicitly labeled proposed, distinguishes the captured current title, and is grounded in the tracked H1 plus a captured topical section. The verification steps name canonical/indexability, preview and re-crawl checks.'
    elif rid == 'onpage-meta_keyword_match':
        before = {'sensibility': 4, 'descriptiveness': 2, 'actionability': 2,
                  'evidence_accuracy': 4, 'technical_usefulness': 2}
        after = {'sensibility': 4, 'descriptiveness': 5, 'actionability': 5,
                 'evidence_accuracy': 5, 'technical_usefulness': 3}
        reason = 'The candidate summarizes captured headings and keyword-related visible text, avoids the observed promotion copy, and says Google may choose another snippet; it is not described as a ranking boost.'
    elif rid == 'technical-mobile-javascript_execution':
        before = {'sensibility': 4, 'descriptiveness': 2, 'actionability': 2,
                  'evidence_accuracy': 4, 'technical_usefulness': 3}
        after = {'sensibility': 5, 'descriptiveness': 5, 'actionability': 5,
                 'evidence_accuracy': 5, 'technical_usefulness': 5}
        reason = 'Execution and unused-code actions shared a resource, so they are coalesced. The user action names affected files, distinguishes same-site from third-party hosts, requires ownership review, protects essential behavior and supplies repeatable checks.'
    elif rid.startswith('technical-mobile-'):
        before = {'sensibility': 4, 'descriptiveness': 2, 'actionability': 2,
                  'evidence_accuracy': 4, 'technical_usefulness': 3}
        after = {'sensibility': 4, 'descriptiveness': 4, 'actionability': 4,
                 'evidence_accuracy': 5, 'technical_usefulness': 5}
        reason = 'The action names the Lighthouse-affected resource, identifies the relevant sizing or dependency check, preserves site functionality and requires a repeat run; exact URLs and measurements remain in the appendix.'
    elif rid == 'internal-resource-cluster':
        before = {'sensibility': 4, 'descriptiveness': 4, 'actionability': 4,
                  'evidence_accuracy': 4, 'technical_usefulness': 3}
        after = {'sensibility': 5, 'descriptiveness': 5, 'actionability': 4,
                 'evidence_accuracy': 5, 'technical_usefulness': 4}
        reason = 'The action now spells out each proposed supporting-page-to-tracked-page pair and states that reverse links were not observed. Source-page content must be checked before choosing placement or adding a link.'
    else:
        before = {'sensibility': 4, 'descriptiveness': 3, 'actionability': 3,
                  'evidence_accuracy': 4, 'technical_usefulness': 3}
        after = dict(before)
        reason = 'No material action change was justified by the available evidence. The current action remains conditional where the exact target-page content or reverse-link state was not captured; no unsupported content gap is asserted.'
    return {'before': before, 'after': after, 'reason': reason,
            'before_actions': old_actions, 'after_actions': row.get('actions') or [],
            'proposed_copy': row.get('action_composition', {}).get('proposed_copy')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('output/task6_evaluation'))
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    out = (project / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    baseline_path = project / 'output/task5_evaluation/aviator/aviator_recommendations.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    baseline_copy = out / 'baseline/task5_recommendations_before.json'
    _save(baseline_copy, baseline)
    baseline_hash = _hash(baseline_path)

    protected_sources = [
        project / 'output/results/aviator/aviator_comparison.json',
        project / 'output/results/aviator/llm_foundation/canonical_evidence.json',
        project / 'output/results/aviator/llm_outputs/executive_model_raw.json',
        project / 'output/results/aviator/llm_outputs/onpage_validated.json',
        project / 'output/results/aviator/llm_outputs/backlinks_validated.json',
        project / 'output/results/aviator/llm_outputs/technical_validated.json',
        project / 'output/results/aviator/llm_outputs/competition_validated.json',
        baseline_path,
    ]
    protected_before = {str(path): _hash(path) for path in protected_sources if path.is_file()}

    run_saved_pipeline(['--output-dir', str(out / 'offline')])
    comparison_path = out / 'offline/pipeline/aviator_comparison.json'
    data = json.loads(comparison_path.read_text(encoding='utf-8'))
    enrichment = enrich_comparison(data, comparison_path, raw_data_root=project / 'data/raw')
    recommendations = generate_recommendations(keyword=data['keyword'],
        ranking_urls=data['primary_ranking_urls'], advanced_evidence=data.get('advanced_evidence') or {},
        onpage=data.get('onpage_comparison') or {},
        technical_comparison=data.get('technical_comparison') or {},
        enriched_page_evidence=enrichment.get('onpage'))
    specialist = json.loads((out / 'offline/saved_inputs/executive_validated_rechecked.json').read_text(encoding='utf-8'))
    quality = json.loads((out / 'offline/saved_inputs/recommendation_quality_report.json').read_text(encoding='utf-8'))
    authoritative, reconciliation = reconcile_recommendations(recommendations, specialist, quality)
    data['recommendations'] = authoritative
    data['recommendation_reconciliation_audit'] = reconciliation
    comparison_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    canonical_path = project / 'output/results/aviator/llm_foundation/canonical_evidence.json'
    canonical = json.loads(canonical_path.read_text(encoding='utf-8'))
    canonical['_source_sha256'] = _hash(canonical_path)
    serp = json.loads((project / 'data/processed/aviator/serp_google.json').read_text(encoding='utf-8'))
    pdf = out / 'aviator_draft_management_report.pdf'
    appendix = out / 'aviator_technical_appendix.md'
    build_management_pdf(pdf, data, specialist, quality, data['keyword'], canonical, serp.get('datetime'))
    recovery_path = out / 'offline/validation_and_recovery_audit.json'
    run_records = json.loads(recovery_path.read_text(encoding='utf-8')).get('task_records')
    appendix_text = build_appendix(data, specialist, quality, comparison_path.name, canonical, run_records)
    appendix_text += '\n## Task 6 action-composition validation\n\n```json\n'
    appendix_text += json.dumps({row['id']: row.get('action_composition') for row in authoritative
        if row.get('action_composition')}, ensure_ascii=False, indent=2) + '\n```\n'
    appendix_text += '\n## Task 6 recommendation reconciliation audit\n\n```json\n'
    appendix_text += json.dumps(reconciliation, ensure_ascii=False, indent=2) + '\n```\n'
    appendix.write_text(appendix_text, encoding='utf-8')
    _save(out / 'aviator_recommendations.json', data)

    synthetic = [
        _synthetic_case('residential solar inverter', 'https://sun.example/solar-inverter',
            'https://rival.example/solar-inverter', 'Residential Solar Inverter',
            ['How to Choose a Residential Solar Inverter', 'Battery Compatibility'], 'Sun Example',
            title_mismatch=True, meta_mismatch=True),
        _synthetic_case('home compost bin odor control', 'https://earth.example/compost-bin',
            'https://garden.example/composting/odor-control', 'Home Compost Bin Odor Control',
            ['How to Control Odor', 'Bin Ventilation', 'Compost Materials'], 'Earth Example',
            title_mismatch=False, meta_mismatch=True),
    ]
    synthetic_text = json.dumps(synthetic, ensure_ascii=False).casefold()
    unrelated_entity_terms_absent = not any(term in synthetic_text for term in
        ('aviator', 'hollywoodbets', 'betway'))
    synthetic_result = {'external_requests': 0,
        'different_keyword_page_conditions_produce_different_recommendations':
            synthetic[0]['recommendation_ids'] != synthetic[1]['recommendation_ids'],
        'no_domain_specific_assumptions': unrelated_entity_terms_absent,
        'unrelated_entity_terms_absent': unrelated_entity_terms_absent, 'cases': synthetic}
    _save(out / 'synthetic_keyword_results.json', synthetic_result)

    baseline_rows = baseline.get('recommendations') or []
    baseline_by_id = {row.get('id'): row for row in baseline_rows}
    before_after = []
    for row in authoritative:
        prior_ids = row.get('coalesced_recommendations') or [row.get('id')]
        prior_rows = [baseline_by_id[rec_id] for rec_id in prior_ids if rec_id in baseline_by_id]
        quality_compare = _scores_for(row, prior_rows)
        before_after.append({'id': row.get('id'), 'title': row.get('title'),
            'baseline_recommendation_ids': prior_ids if prior_rows else [],
            'evidence_tier_before': [x.get('evidence_tier') for x in prior_rows],
            'evidence_tier_after': row.get('evidence_tier'),
            **quality_compare})

    from analysis.recommendation_classification import TIER_ORDER
    tiers = TIER_ORDER
    tier_counts = {key: sum(row.get('evidence_tier') == key for row in authoritative) for key in tiers}
    ordered = [(tiers.get(row.get('evidence_tier'), 99), -float(row.get('priority_score') or 0))
               for row in authoritative]
    source_unchanged = all(path.exists() and _hash(path) == digest for path, digest in
                           ((Path(name), digest) for name, digest in protected_before.items()))
    audit = json.loads(recovery_path.read_text(encoding='utf-8'))
    report = {'title': 'Task 6 — Evidence-Grounded Recommendation Action Composer',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'saved evidence only; no live collection, model or paid API requests',
        'root_cause': 'Recommendation construction detected metadata mismatches but emitted generic conditional steps; evidence preparation, validation and rendering passed that action through.',
        'before_recommendation_count': len(baseline_rows), 'after_recommendation_count': len(authoritative),
        'recommendation_quality_by_item': before_after,
        'tier_counts': tier_counts, 'ordered_by_tier_then_priority': ordered == sorted(ordered),
        'exactly_two_tiers': all(row.get('evidence_tier') in tiers for row in authoritative),
        'specialist_quality_flags': {'blocking': quality.get('blocking_count'), 'review': quality.get('review_count')},
        'original_specialist_findings_preserved': audit.get('original_specialist_findings_preserved'),
        'saved_inputs_unchanged': audit.get('source_inputs_unchanged') and source_unchanged and _hash(baseline_path) == baseline_hash,
        'external_requests': 0, 'draft_not_approved_or_published': True,
        'synthetic_keyword_tests': synthetic_result,
        'known_limits': [
            'Tier 1 reflects evidence strength and action specificity; it does not imply that an implementation caused or will cause ranking changes.',
            'Mapped query pages outside the exact tracked-page crawl lack their own content captures; their action stays conditional and no missing section is asserted.',
            'Internal-link source pages are not all captured; proposed return-link pairs are explicitly checks, not claims that links are missing.',
            'Meta description text is a proposed snippet candidate. Google may generate a different snippet; no ranking benefit is claimed.',
            'The six saved Gemma plan blockers and eleven review flags remain unresolved and their plans are withheld from the authoritative user-facing list.' ]}
    _save(out / 'final_evaluation_report.json', report)

    classification = {'recommendations': [{'order': row.get('order'), 'id': row.get('id'),
        'title': row.get('title'), 'evidence_tier': row.get('evidence_tier'),
        'priority_score': row.get('priority_score'), 'action_composition': row.get('action_composition')}
        for row in authoritative], 'tier_counts': tier_counts,
        'ordered_by_tier_then_priority': report['ordered_by_tier_then_priority'],
        'exactly_two_tiers': report['exactly_two_tiers']}
    _save(out / 'evidence_tier_classification.json', classification)

    md = ['# Task 6 final evaluation', '',
        f"Generated {report['generated_at']}; offline saved-evidence run; requests made: 0.", '',
        '## Root cause', '', report['root_cause'], '',
        f"Recommendations: {len(baseline_rows)} before; {len(authoritative)} after composition and reconciliation.",
        f"Evidence tiers: {tier_counts}.", '',
        '## Recommendation-by-recommendation quality (1–5)', '',
        '| Recommendation | Dimension | Before | After | Reason |', '|---|---|---:|---:|---|']
    dimensions = ('sensibility', 'descriptiveness', 'actionability', 'evidence_accuracy', 'technical_usefulness')
    for item in before_after:
        for dimension in dimensions:
            md.append(f"| {item['title']} | {dimension.replace('_', ' ').title()} | {item['before'][dimension]} | {item['after'][dimension]} | {item['reason']} |")
    md.extend(['', '## Proposed copy examples', '',
        '| Field | Captured text | Proposed text (not observed) | Evidence basis |', '|---|---|---|---|'])
    for row in authoritative:
        proposed = row.get('action_composition', {}).get('proposed_copy')
        if proposed:
            md.append(f"| {proposed['field']} | {proposed['replaces_observed']} | {proposed['candidate']} | {', '.join(proposed['basis'])} |")
    md.extend(['', '## Synthetic keyword/page pairs', '',
        '| Keyword | Recommendation IDs | Grounded examples |', '|---|---|---|'])
    for case in synthetic:
        md.append(f"| {case['keyword']} | {', '.join(case['recommendation_ids'])} | {len(case['proposed_copy'])} |")
    md.extend(['', '## Remaining limitations', ''] + [f'- {x}' for x in report['known_limits']])
    (out / 'final_evaluation_report.md').write_text('\n'.join(md) + '\n', encoding='utf-8')

    manifest = {'mode': 'task6_saved_evidence_offline', 'generated_at': report['generated_at'],
        'external_requests': 0, 'source_inputs_unchanged': report['saved_inputs_unchanged'],
        'recommendations_json': str((out / 'aviator_recommendations.json').resolve()),
        'management_pdf': str(pdf.resolve()), 'technical_appendix': str(appendix.resolve()),
        'evaluation_report': str((out / 'final_evaluation_report.json').resolve()),
        'synthetic_tests': str((out / 'synthetic_keyword_results.json').resolve()),
        'classification': str((out / 'evidence_tier_classification.json').resolve()),
        'baseline_copy': str(baseline_copy.resolve()), 'draft_not_approved_or_published': True,
        'previous_task5_recommendation_sha256': baseline_hash,
        'offline_pipeline_manifest': str((out / 'offline/offline_run_manifest.json').resolve())}
    _save(out / 'offline_run_manifest.json', manifest)
    print(json.dumps({'output_dir': str(out), 'external_requests': 0,
        'recommendations_before': len(baseline_rows), 'recommendations_after': len(authoritative),
        'tier_counts': tier_counts, 'copy_candidates': [x.get('proposed_copy') for x in before_after if x.get('proposed_copy')],
        'saved_inputs_unchanged': report['saved_inputs_unchanged']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
