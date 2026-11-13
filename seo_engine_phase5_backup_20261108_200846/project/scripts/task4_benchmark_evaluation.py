"""Write Task 4 benchmark comparison and criterion scores from saved evidence."""
from __future__ import annotations

import json
from pathlib import Path


def main():
    project = Path(__file__).resolve().parents[1]
    out = project / 'output/task4_evaluation/aviator'
    reference_text = next(project.glob('development_references/OUTPUTSERP*.txt'))
    reference_pdf = next(project.glob('development_references/aviator_executive_report*.pdf'))
    old = json.loads((project / 'output/task3_evaluation/aviator/quality_evaluation_report.json').read_text(encoding='utf-8'))
    new = json.loads((out / 'pipeline/aviator_comparison.json').read_text(encoding='utf-8'))
    plans = json.loads((out / 'saved_inputs/executive_validated_rechecked.json').read_text(encoding='utf-8'))
    quality = json.loads((out / 'saved_inputs/recommendation_quality_report.json').read_text(encoding='utf-8'))
    ids = [row['id'] for row in new['recommendations']]
    scores = [
        {'criterion': 'Sensibility', 'before': 3, 'after': 4,
         'reason': 'The current recommendations rely on exact saved query-result URLs and crawled links, phrase changes conditionally, and correct the demo-page contradiction. Potential impact remains qualified; no ranking cause is asserted.'},
        {'criterion': 'Descriptiveness', 'before': 4, 'after': 4,
         'reason': 'Each management card states observed difference, potential impact and implementation steps. Technical Lighthouse resource actions remain dense because multiple audited resources are handled in one card.'},
        {'criterion': 'Actionability', 'before': 3, 'after': 4,
         'reason': 'Actions name exact existing query landing pages, link candidates and destinations; on-page edits require rendered verification; technical changes have resource checks and functionality safeguards.'},
        {'criterion': 'Evidence accuracy', 'before': 3, 'after': 4,
         'reason': 'Exact URL mapping, same-domain result filtering, identity-matched raw link enrichment, Lighthouse diagnostics and internal-link direction caveats are checked. Saved specialist plan audit still reports blocking issues and remains review-only.'},
        {'criterion': 'Technical quality', 'before': 3, 'after': 4,
         'reason': 'Lighthouse actions map to named resources and explicitly protect fraud/security scripts, payment, consent and core interactions. The implementation is still a proposed triage, not a live functional test.'},
        {'criterion': 'Coverage', 'before': 2, 'after': 4,
         'reason': 'The current set spans technical performance, existing demo discoverability, existing query landing pages, title/meta and internal resources. FAQ demand and editorial backlink prospects are correctly withheld for missing evidence.'},
    ]
    report = {
        'title': 'Task 4 — Benchmark-Driven Recommendation Evaluation',
        'mode': 'saved evidence only; no model, API, network, publication or approval requests',
        'reference_files_resolved': [str(reference_text.relative_to(project)), str(reference_pdf.relative_to(project))],
        'comparison': {
            'before_recommendation_ids': old['before_after']['current_deterministic'],
            'after_recommendation_ids': ids,
            'historical_reference_gaps_addressed': [
                'Reused the existing first-party demo page surfaced by the saved query result; did not advise creating a duplicate page.',
                'Restored six exact internal destination URLs from identity-matched raw page capture and framed reverse links as conditional because inbound link evidence is unavailable.',
                'Mapped instructional query intent to an existing first-party article and prohibited duplicate content.',
                'Withheld FAQ recommendation because query/PAA demand and candidate page content were not captured.',
                'Withheld backlink outreach because aggregate counts contain no verified editorial publisher prospects.',
                'Kept Lighthouse fixes tied to observed resources and preserved fraud prevention/security functionality.'
            ],
            'reference_limitations_retained': [
                'Reference link count (44 vs 13), word count and referring-domain observations differ from the current saved capture; treated as historical reference values, not current evidence.',
                'Neither the reference report nor this run establishes ranking causality.',
            ],
            'phase1_3_traceability_findings': str((project / 'output/task4_preimplementation/phase1_3_evidence_traceability.md').relative_to(project)),
        },
        'scores_1_to_5': scores,
        'evidence_tiers': {
            'deterministic_counts': json.loads((out / 'recommendation_classification_results.json').read_text(encoding='utf-8'))['tier_counts'],
            'focused_saved_plan_counts': json.loads((out / 'recommendation_classification_results.json').read_text(encoding='utf-8'))['focused_tier_counts'],
            'tier_rule_checks': json.loads((out / 'recommendation_classification_results.json').read_text(encoding='utf-8'))['tier_rule_checks'],
            'unsupported_observation_claims_ineligible': True,
            'incomplete_observations_preserved_in_audit': True,
            'duplicate_recommendations': 'Query rows are grouped by normalized exact first-party landing URL; only the highest-volume row per URL is proposed. Distinct URLs remain separate.',
        },
        'focused_saved_response_validation': {
            'implementation_plans': len(plans.get('implementation_plans', [])),
            'blocking_flags': quality.get('blocking_count'), 'review_flags': quality.get('review_count'),
            'all_original_specialist_findings_preserved': json.loads((out / 'llm_outputs/information_preservation_report.json').read_text(encoding='utf-8'))['all_original_findings_preserved'],
            'note': 'Specialist plans were revalidated and preserved for traceability; six blocker-level quality findings remain. These plans are not substituted into the deterministic recommendation list.'
        },
        'limitations': [
            'Scores are comparative rubric judgments, not measured search outcomes.',
            'No controlled historical outcome evidence is available, so no current recommendation qualifies for Tier 1.',
            'Saved specialist responses still have six blocking and eleven review flags after offline validation.',
            'Current crawl is point-in-time and does not reveal incoming internal links, FAQ demand, Search Console outcomes or link prospect context.',
        ],
    }
    (out / 'quality_evaluation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# Task 4 quality evaluation', '',
             'All artifacts were produced from saved local evidence. No live Gemma, paid API or publication request was made.', '',
             '## Before and after', '',
             f"Before: {', '.join(old['tier_results']['deterministic'])}",
             f"After: {', '.join(ids)}", '',
             'Key differences: exact existing query landing pages are named; six source-to-target candidates use saved crawl links with direction caveats; the existing demo result is surfaced; FAQ and link acquisition remain withheld without demand/prospect evidence.', '',
             '## Scores', '', '| Criterion | Before | After | Reason |', '|---|---:|---:|---|']
    lines.extend(f"| {row['criterion']} | {row['before']}/5 | {row['after']}/5 | {row['reason']} |" for row in scores)
    lines += ['', '## Tier results', '', f"Deterministic recommendations: {report['evidence_tiers']['deterministic_counts']}",
              f"Saved specialist plans: {report['evidence_tiers']['focused_saved_plan_counts']}",
              'No recommendation qualifies for Tier 1 because the saved investigation contains no credible controlled outcome evidence.', '',
              '## Remaining limitations', '']
    lines.extend(f'- {item}' for item in report['limitations'])
    (out / 'quality_evaluation_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(str(out / 'quality_evaluation_report.md'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
