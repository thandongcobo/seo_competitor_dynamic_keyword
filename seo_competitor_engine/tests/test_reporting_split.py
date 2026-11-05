"""Offline regression checks for management brief and full technical appendix."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.generate_executive_pdf import (
    build_appendix, build_management_pdf, main, report_consistency_errors,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'output/gemma_tests/aviator/quality_v4_review_repair/executive_quality_repaired.json'
COMPARISON = ROOT / 'output/results/aviator/aviator_comparison.json'


def read_sample():
    return json.loads(SAMPLE.read_text(encoding='utf-8'))


def _report_row(title, tier, score, *, uncertainty=False):
    row = {'title': title, 'evidence_tier': tier, 'priority_score': score,
        'id': title.lower().replace(' ', '-'), 'target_url': 'https://site.example/page',
        'evidence': 'The exact page capture confirms the observed page element.',
        'interpretation': 'A grounded change may improve clarity for users.',
        'action_justification': 'The proposed change is supported by the captured page evidence.',
        'display_action': 'Replace the captured page element with the grounded proposed value and verify the rendered page.',
        'actions': ['Replace the captured page element with the grounded proposed value and verify the rendered page.'],
        'validation_status': 'validated_rule_evidence',
        'evidence_provenance': {'source': 'identity-matched page capture',
            'observation': 'The exact page capture confirms the observed page element.',
            'target_url': 'https://site.example/page', 'evidence_ids': ['PAGE_ELEMENT']},
        'action_composition': {'proposed_copy': {'field': 'title', 'candidate': 'Page Topic | Example',
            'status': 'proposed_not_observed', 'source_evidence_ids': ['PAGE_ELEMENT'],
            'validation': {'grounded': True}}}}
    if uncertainty:
        row['limitations'] = 'The related page content was not captured; confirm the exact weakness before editing.'
        row['action_composition'] = {'status': 'existing_query_page_named_but_its_content_was_not_captured'}
    return row


def test_lineage_preserved_for_saved_evidence():
    ex = read_sample()
    assert len(ex['implementation_plans']) == 7
    assert len(ex['finding_dispositions']) == 11
    assert len(ex['specialist_findings']) == 11
    assert not report_consistency_errors(ex)


def test_missing_disposition_is_rejected():
    ex = read_sample()
    ex['finding_dispositions'].pop()
    assert report_consistency_errors(ex)


def test_appendix_preserves_all_original_observations_and_actions():
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    from llm_foundation.recommendation_quality import audit_recommendations
    quality = audit_recommendations(ex)
    appendix = build_appendix(data, ex, quality, 'comparison.json')
    for p in ex['implementation_plans']:
        assert p['title'] in appendix
        for step in p['implementation_steps']:
            assert step in appendix
    for original in ex['specialist_findings']:
        assert original['id'] in appendix
        assert original['finding']['observation'] in appendix
    for disposition in ex['finding_dispositions']:
        assert disposition['specialist_finding_id'] in appendix
    for fact in ex['verified_factual_findings']:
        assert fact['statement'] in appendix
    assert 'historical evidence' in appendix


def test_appendix_includes_evidence_provenance_and_saved_run_records():
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    canonical = json.loads((ROOT / 'output/results/aviator/llm_foundation/canonical_evidence.json').read_text(encoding='utf-8'))
    canonical['_source_sha256'] = 'synthetic-sha256'
    records = [{'task': task, 'status': 'validated', 'attempts': 2,
                'recovery_status': 'validated', 'review_finding_ids': [],
                'recovery_audit': {'status': 'not_recovered', 'fixture_record': 'preserved'},
                'diagnostics': [{'validation_errors': ['fixture validation record']} ]}
               for task in ('onpage', 'backlinks', 'technical', 'competition')]
    from llm_foundation.recommendation_quality import audit_recommendations
    appendix = build_appendix(data, ex, audit_recommendations(ex), 'comparison.json', canonical, records)
    assert 'evidence.onpage.pages' in appendix
    assert 'evidence.backlinks.page' in appendix
    assert 'synthetic-sha256' in appendix
    assert 'Validation and recovery records' in appendix
    assert '**competition:** status=validated; attempts=2' in appendix
    assert 'fixture_record' in appendix and 'fixture validation record' in appendix


def test_management_brief_renders_without_long_raw_evidence(tmp_path):
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    pdf = tmp_path / 'brief.pdf'
    build_management_pdf(pdf, data, ex, {'blocking_count': 0, 'review_count': 0}, 'aviator')
    assert pdf.read_bytes()[:4] == b'%PDF'
    fitz = pytest.importorskip('fitz')
    doc = fitz.open(pdf)
    assert 2 <= len(doc) <= 7
    text = '\n'.join(page.get_text() for page in doc)
    assert 'Difference Observed:' in text
    assert 'Potential Impact:' in text
    assert 'Recommended Action:' in text
    assert 'Original specialist findings' not in text


def test_management_pdf_groups_tiers_and_uses_three_plain_language_sections(tmp_path):
    ex = read_sample()
    comparison = json.loads(COMPARISON.read_text(encoding='utf-8'))
    comparison['recommendations'] = [
        _report_row('Moderate opportunity', 'tier_3_plausible_opportunity', 100, uncertainty=True),
        _report_row('Previously historical', 'tier_1_historically_supported', 1),
        _report_row('Previously evidence-supported', 'tier_2_evidence_supported', 50),
    ]
    pdf = tmp_path / 'tiered-management-brief.pdf'
    build_management_pdf(pdf, comparison, ex, {'blocking_count': 0, 'review_count': 0}, 'aviator')
    fitz = pytest.importorskip('fitz')
    text = '\n'.join(page.get_text() for page in fitz.open(pdf))
    assert 'Tier 1 — Strong Evidence' in text
    assert 'Tier 2 — Moderate Evidence' in text
    assert 'Tier 3' not in text
    for heading in ('Difference Observed:', 'Potential Impact:', 'Recommended Action:'):
        assert heading in text
    assert 'Evidence / specialist IDs' not in text
    assert 'technical appendix contains the full implementation steps' in text.lower()


def test_management_pdf_prefers_tiered_saved_recommendations_without_internal_ids(tmp_path):
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    data['recommendations'] = [
        {**_report_row('Moderate opportunity', 'tier_3_plausible_opportunity', 99, uncertainty=True), 'specialist_finding_ids': ['INTERNAL_3']},
        {**_report_row('Historically supported', 'tier_1_historically_supported', 1), 'specialist_finding_ids': ['INTERNAL_1']},
        {**_report_row('Evidence-supported', 'tier_2_evidence_supported', 20), 'specialist_finding_ids': ['INTERNAL_2']},
    ]
    pdf = tmp_path / 'saved-recommendations.pdf'
    build_management_pdf(pdf, data, ex, {'blocking_count': 0, 'review_count': 0}, 'aviator')
    fitz = pytest.importorskip('fitz')
    text = '\n'.join(page.get_text() for page in fitz.open(pdf))
    assert text.index('Tier 1 — Strong Evidence') < text.index('Tier 2 — Moderate Evidence')
    assert 'Tier 3' not in text
    assert 'The exact page capture confirms' in text
    assert 'INTERNAL_1' not in text


def test_management_pdf_hides_resource_urls_but_keeps_them_in_appendix(tmp_path):
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    resource = 'https://cdn.example.test/assets/large-hero-image.webp'
    data['recommendations'] = [{
        'id': 'technical-mobile-image_delivery',
        'title': 'Improve image delivery on the tracked page',
        'evidence_tier': 'tier_2_evidence_supported', 'priority_score': 10,
        'target_url': 'https://site.example/page', 'action_justification': 'Resize only if needed.',
        'validation_status': 'validated_rule_evidence',
        'evidence': f'Lighthouse image diagnostic: {resource} (70000 wastedBytes).',
        'interpretation': 'Optimising the image may reduce image delivery work.',
        'display_action': f'Optimise {resource} safely and verify the page.',
        'actions': [f'Inspect {resource} and retain image quality.'],
        'evidence_provenance': {'source': 'Lighthouse exact-page diagnostics',
            'target_url': 'https://site.example/page', 'resource_candidates': [{'url': resource}]},
        'action_composition': {'status': 'specific_resource_action_composed', 'resource_names': ['large-hero-image.webp']},
    }]
    pdf = tmp_path / 'sanitised-management-brief.pdf'
    build_management_pdf(pdf, data, ex, None, 'aviator')
    fitz = pytest.importorskip('fitz')
    text = '\n'.join(page.get_text() for page in fitz.open(pdf))
    assert resource not in text
    assert 'wastedBytes' not in text
    assert 'Lighthouse run flagged image delivery' in text
    appendix = build_appendix(data, ex, None, 'comparison.json')
    assert resource in appendix


def test_management_pdf_and_appendix_preserve_proposed_copy_distinction(tmp_path):
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    candidate = 'AeroPress Coffee Maker: Brewing Guide | Example'
    data['recommendations'] = [{
        'id': 'onpage-title_keyword_match', 'title': 'Improve the HTML title',
        'evidence_tier': 'tier_3_plausible_opportunity', 'priority_score': 10,
        'target_url': 'https://site.example/page', 'action_justification': 'Grounded in observed title and H1.',
        'validation_status': 'validated_rule_evidence',
        'evidence': 'Observed title: "Kitchen Products | Example".',
        'interpretation': 'A descriptive title may communicate page topic.',
        'display_action': f'Proposed title (not observed): "{candidate}". Preview and verify it.',
        'actions': [f'Use proposed title (not observed): "{candidate}".'],
        'evidence_provenance': {'source': 'identity-matched page capture', 'target_url': 'https://site.example/page',
            'evidence_ids': ['PAGE_TITLE','PAGE_H1']},
        'action_composition': {'status': 'candidate_proposed_from_identity_matched_page_evidence',
            'proposed_copy': {'field': 'title', 'candidate': candidate,
                'replaces_observed': 'Kitchen Products | Example', 'status': 'proposed_not_observed',
                'source_evidence_ids': ['PAGE_TITLE','PAGE_H1'], 'validation': {'grounded': True}}},
    }]
    pdf = tmp_path / 'proposed-copy.pdf'
    build_management_pdf(pdf, data, ex, None, 'coffee maker')
    assert pdf.read_bytes()[:4] == b'%PDF'
    appendix = build_appendix(data, ex, None, 'comparison.json')
    assert candidate in appendix
    assert 'proposed_not_observed' in appendix


def test_end_to_end_offline_and_source_integrity(tmp_path):
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (SAMPLE, COMPARISON)]
    manifest = main(['--keyword', 'aviator', '--input', str(COMPARISON),
                     '--executive-json', str(SAMPLE), '--output-dir', str(tmp_path)])
    assert manifest['implementation_plan_count'] == 7
    assert manifest['finding_disposition_count'] == 11
    assert manifest['original_specialist_finding_count'] == 11
    assert manifest['verified_factual_finding_count'] == 8
    assert manifest['blocking_quality_flags'] == 0
    assert (tmp_path / 'aviator_executive_report.pdf').exists()
    assert (tmp_path / 'aviator_technical_appendix.md').exists()
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (SAMPLE, COMPARISON)]


def test_generic_keyword_and_domains(tmp_path):
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    data['our_domain'] = 'example-one.test'
    data['benchmark_competitor_domain'] = 'example-two.test'
    data['ranking_summary']['google']['our_position'] = 8
    data['ranking_summary']['google']['benchmark_position'] = 5
    pdf = tmp_path / 'generic.pdf'
    build_management_pdf(pdf, data, ex, None, 'test-query')
    fitz = pytest.importorskip('fitz')
    text = '\n'.join(p.get_text() for p in fitz.open(pdf))
    assert 'example-one.test' in text
    assert 'example-two.test' in text
    assert '#8' in text and '#5' in text


def test_management_brief_shows_exact_urls_date_and_search_context(tmp_path):
    ex = read_sample()
    data = json.loads(COMPARISON.read_text(encoding='utf-8'))
    canonical = {
        'investigation': {'search_engine': 'Google', 'market': 'Synthetic market'},
        'tracked_website': {'ranking_url': 'https://alpha.example.test/topic/page-a'},
        'competitors': [{'ranking_url': 'https://beta.example.test/guide/page-b'}],
    }
    pdf = tmp_path / 'identity.pdf'
    build_management_pdf(pdf, data, ex, None, 'sample query', canonical,
                         '2026-11-03T08:30:00Z')
    fitz = pytest.importorskip('fitz')
    text = '\n'.join(page.get_text() for page in fitz.open(pdf))
    assert 'https://alpha.example.test/topic/page-a' in text
    assert 'https://beta.example.test/guide/page-b' in text
    assert '2026-11-03T08:30:00Z' in text
    assert 'Synthetic market' in text


def test_rejects_blocking_quality_and_keeps_output_empty(tmp_path):
    ex = read_sample()
    ex['implementation_plans'][0]['simple_explanation'] = 'We are losing many users.'
    p = tmp_path / 'invalid.json'
    p.write_text(json.dumps(ex), encoding='utf-8')
    out = tmp_path / 'report'
    with pytest.raises(ValueError, match='Blocking quality flags|Blocking quality flags remain'):
        main(['--keyword', 'aviator', '--input', str(COMPARISON),
              '--executive-json', str(p), '--output-dir', str(out)])
    assert not out.exists()


def test_no_llm_or_collectors_in_report_generator():
    import inspect
    import scripts.generate_executive_pdf as module
    source = inspect.getsource(module)
    assert 'chat.completions.create' not in source
    assert 'DataForSEO(' not in source
