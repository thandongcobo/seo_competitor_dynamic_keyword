"""Offline regression checks for V4 verification language and repaired-report provenance."""
import copy
import json
from pathlib import Path

import pytest

from llm_foundation.recommendation_quality import (
    audit_recommendations,
    missing_post_change_verification,
)
from scripts import generate_executive_pdf


def plan(steps):
    return {'title': 'Script delivery review', 'evidence_ids': [],
            'implementation_steps': steps, 'technical_explanation': 'Inspect the bundle carefully.'}


def test_post_deployment_verification_and_remeasuring_are_recognized():
    item = plan([
        'Implement the approved JavaScript change.',
        'Perform a post-deployment verification by re-measuring bundle size and boot-up time.',
    ])
    assert not missing_post_change_verification(item)


def test_before_only_verification_does_not_satisfy_post_change_check():
    item = plan([
        'Verify baseline bundle size before release.',
        'Deploy the approved change.',
    ])
    assert missing_post_change_verification(item)


def test_unrelated_post_change_comment_does_not_count_as_measurement():
    item = plan(['Implement a change.', 'After deployment, notify the team.'])
    assert missing_post_change_verification(item)


def test_after_release_confirming_metrics_is_valid():
    item = plan(['Implement the change.', 'After release, confirm the updated performance metrics.'])
    assert not missing_post_change_verification(item)


def sample_executive():
    def item(n):
        return {
            'title': f'CURRENT REPAIRED PLAN {n}', 'owner': 'SEO', 'priority': 'high',
            'implementation_steps': ['Update the verified page element.', 'Deploy the approved change.', 'Verify the rendered result after release.'],
            'rationale': 'A measured difference supports a scoped page improvement hypothesis, with ranking effect unknown.',
            'success_measure': f'CURRENT SUCCESS CHECK {n}',
            'uncertainty': 'Effects are unverified.',
            'simple_explanation': 'A visible difference supports improving this page; ranking effects remain uncertain.',
            'technical_explanation': 'Update the verified element on the exact selected page, preserve existing functionality, and check the rendered result after deployment using the same saved measurement method.',
            'specialist_finding_ids': [f'F{n}'], 'evidence_ids': ['FACT'],
        }
    return {
        'schema_version': '1.0', 'executive_summary': 'Historical observation only.',
        'verified_factual_summary': 'Historical facts.',
        'key_findings': [],
        'verified_factual_findings': [
            {'statement': 'Verified fact from saved data', 'interpretation': 'Observed difference.',
             'why_it_matters': 'Further study is warranted.', 'next_check': 'Repeat under matched conditions.',
             'limitation': 'No causal claim.', 'evidence_ids': ['FACT']},
        ],
        'implementation_plans': [item(1), item(2)],
        'finding_dispositions': [
            {'specialist_finding_id': f'F{n}', 'outcome': 'action', 'plan_indices': [n-1],
             'simple_explanation': 'Business interpretation.', 'technical_explanation': 'Technical interpretation.',
             'next_step': 'Investigate.', 'reason': 'Measured evidence.', 'evidence_ids': ['FACT']}
            for n in (1, 2)
        ],
        'specialist_findings': [
            {'id': f'F{n}', 'task': 'onpage', 'source': f'original/{n}',
             'finding': {'observation': 'Saved observation.', 'evidence_paths': ['source.path']}}
            for n in (1, 2)
        ],
        'proposed_decisions': [{'title': 'STALE EXECUTIVE DECISION', 'owner': 'Old', 'success_check': 'Old'}],
        'recommended_improvements': [{'action': 'STALE OLD RECOMMENDATION'}],
        'potential_ranking_explanations': [], 'hollywoodbets_strengths': [],
        'hollywoodbets_weaknesses_opportunities': [], 'limitations': ['Single observation.'],
    }


def test_explicit_repaired_json_generates_current_plans_and_facts(tmp_path, monkeypatch):
    executive = sample_executive()
    source = tmp_path / 'repaired.json'
    comparison = tmp_path / 'comparison.json'
    out = tmp_path / 'new_report'
    source.write_text(json.dumps(executive), encoding='utf-8')
    comparison.write_text(json.dumps({'our_domain':'ours.example','benchmark_competitor_domain':'other.example',
                                     'ranking_summary':{'google':{'our_position':2,'benchmark_position':1}}}), encoding='utf-8')
    monkeypatch.setattr(generate_executive_pdf, 'generate_report', lambda *a, **kw: '# Existing deterministic analysis\n')
    generate_executive_pdf.main(['--keyword','sample','--input',str(comparison),
                                 '--executive-json',str(source),'--output-dir',str(out)])
    manifest = json.loads((out/'report_generation_manifest.json').read_text(encoding='utf-8'))
    appendix = (out/'sample_technical_appendix.md').read_text(encoding='utf-8')
    assert manifest['implementation_plan_count'] == 2
    assert manifest['finding_disposition_count'] == 2
    assert manifest['verified_factual_finding_count'] == 1
    assert manifest['blocking_quality_flags'] == 0
    assert manifest['source_executive_json'] == str(source.resolve())
    assert 'CURRENT REPAIRED PLAN 1' in appendix and 'CURRENT REPAIRED PLAN 2' in appendix
    assert 'Verified fact from saved data' in appendix
    assert 'STALE OLD RECOMMENDATION' not in appendix
    assert (out/'sample_executive_report.pdf').stat().st_size > 1000
    assert json.loads(source.read_text(encoding='utf-8')) == executive  # input untouched


def test_explicit_repaired_json_does_not_fallback_to_old_json(tmp_path):
    with pytest.raises(FileNotFoundError, match='Explicit repaired executive JSON'):
        generate_executive_pdf.main(['--keyword','x','--input',str(tmp_path/'comparison.json'),
                                     '--executive-json',str(tmp_path/'missing.json'),
                                     '--output-dir',str(tmp_path/'out')])


def test_repaired_report_fails_closed_when_factual_findings_missing(tmp_path):
    ex = sample_executive()
    ex['verified_factual_findings'] = []
    src = tmp_path/'ex.json'
    comparison = tmp_path/'comparison.json'
    src.write_text(json.dumps(ex),encoding='utf-8')
    comparison.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError, match='verified factual findings'):
        generate_executive_pdf.main(['--keyword','x','--input',str(comparison),
                                     '--executive-json',str(src), '--output-dir',str(tmp_path/'out')])


def test_lineage_consistency_rejects_missing_reciprocal_plan_link():
    ex=sample_executive()
    assert generate_executive_pdf.report_consistency_errors(ex)==[]
    ex['finding_dispositions'][0]['plan_indices']=[1]
    errors=generate_executive_pdf.report_consistency_errors(ex)
    assert any('reciprocal' in error for error in errors)


def test_lineage_consistency_rejects_missing_original_finding():
    ex=sample_executive()
    ex['finding_dispositions'].pop()
    assert any('coverage' in error for error in generate_executive_pdf.report_consistency_errors(ex))
