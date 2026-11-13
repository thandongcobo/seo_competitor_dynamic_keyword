from copy import deepcopy

from analysis.recommendation_classification import (
    TIER_1, TIER_2, adapt_comparison, adapt_recommendations, classify_recommendation,
)
from analysis.recommendations import classify_evidence_tier


def _row(**overrides):
    row = {
        'id': 'sample', 'title': 'Improve the page title',
        'target_url': 'https://site.example/page',
        'evidence': 'The captured page title omits the topic shown in its H1.',
        'interpretation': 'A more accurate title can better communicate the page topic.',
        'action_justification': 'The proposed wording uses the verified page topic.',
        'display_action': 'Replace the current title with the grounded candidate and verify rendered HTML.',
        'actions': ['Replace the captured title and verify rendered HTML.'],
        'evidence_provenance': {
            'source': 'identity-matched page capture',
            'observation': 'Captured title and H1 differ in topic wording.',
            'target_url': 'https://site.example/page',
            'evidence_ids': ['PAGE_TITLE', 'PAGE_H1'],
        },
        'validation_status': 'validated_rule_evidence',
        'recovery_status': 'not_required',
        'priority_score': 4,
        'evidence_tier': 'tier_3_plausible_opportunity',
    }
    row.update(overrides)
    return row


def test_strong_verified_specific_action_does_not_need_historical_outcomes():
    row = _row(action_composition={
        'proposed_copy': {'candidate': 'Page topic guide', 'status': 'proposed_not_observed',
                          'validation': {'grounded': True}, 'source_evidence_ids': ['PAGE_TITLE']}})
    result, audit = classify_recommendation(row)
    assert result['evidence_tier'] == TIER_1
    assert result['classification_version'] == 2
    assert result['legacy_evidence_tier'] == 'tier_3_plausible_opportunity'
    assert audit['observation_verified'] and audit['action_supported']
    assert 'historical_outcome' not in result['classification_assessment']


def test_moderate_evidence_maps_old_tier_three_to_tier_two():
    row = _row(evidence_tier='tier_3_plausible_opportunity',
        limitations='The supporting page content was not captured; verify it before editing.')
    result, audit = classify_recommendation(row)
    assert result['evidence_tier'] == TIER_2
    assert result['legacy_evidence_tier'] == 'tier_3_plausible_opportunity'
    assert audit['material_uncertainty'] is True


def test_unsupported_or_unverified_record_is_excluded_and_audited():
    row = _row(unsupported_claims=True)
    result, audit = classify_recommendation(row)
    assert result is None
    assert audit['eligible'] is False
    assert audit['unsupported_claims_detected'] is True
    assert audit['recommendation_id'] == 'sample'


def test_numeric_difference_and_priority_alone_never_make_tier_one():
    assert classify_evidence_tier(observation_verified=True, action_supported=True,
        established_principle=False, exact_scope_verified=True, action_specific=True) is None
    row = _row(evidence='Position difference: tracked page #2, competitor #1.',
        interpretation='', action_justification='', display_action='Improve by 1 position.',
        priority_score=100, evidence_provenance={'source': 'rank snapshot',
            'observation': 'Position difference', 'target_url': 'https://site.example/page'})
    result, _ = classify_recommendation(row)
    assert result is None


def test_old_tier_one_and_two_are_reassessed_and_source_records_not_mutated():
    grounded = {'proposed_copy': {'candidate': 'Page topic | Example',
        'status': 'proposed_not_observed', 'validation': {'grounded': True},
        'source_evidence_ids': ['PAGE_TITLE']}}
    old = [_row(id='old1', evidence_tier='tier_1_historically_supported', action_composition=grounded),
           _row(id='old2', evidence_tier='tier_2_evidence_supported', action_composition=grounded)]
    original = deepcopy(old)
    adapted, audit = adapt_recommendations(old)
    assert old == original
    assert [row['evidence_tier'] for row in adapted] == [TIER_1, TIER_1]
    assert [row['legacy_evidence_tier'] for row in adapted] == [
        'tier_1_historically_supported', 'tier_2_evidence_supported']
    assert audit['classification_version'] == 2


def test_priority_is_independent_and_orders_within_evidence_tier():
    rows = [_row(id='low', priority_score=2),
            _row(id='strong', priority_score=40, action_composition={
                'proposed_copy': {'candidate': 'Grounded', 'status': 'proposed_not_observed',
                                  'validation': {'grounded': True}, 'source_evidence_ids': ['PAGE_TITLE']}})]
    adapted, _ = adapt_recommendations(rows)
    assert [row['evidence_tier'] for row in adapted] == [TIER_1, TIER_2]
    adapted, _ = adapt_recommendations([rows[0], {**rows[0], 'id': 'higher', 'priority_score': 7}])
    assert [row['id'] for row in adapted] == ['higher', 'low']


def test_task6_rows_are_reassessed_using_action_and_uncertainty_not_old_tier():
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / 'output/task6_evaluation/aviator_recommendations.json').read_text(encoding='utf-8'))
    rows, audit = adapt_recommendations(data['recommendations'])
    by_id = {row['id']: row for row in rows}
    assert by_id['onpage-title_keyword_match']['evidence_tier'] == TIER_1
    assert by_id['onpage-meta_keyword_match']['evidence_tier'] == TIER_1
    assert by_id['technical-mobile-image_delivery']['evidence_tier'] == TIER_1
    for rid in ('technical-mobile-javascript_execution', 'technical-mobile-render_blocking',
                'internal-resource-cluster', 'existing-query-page-249fa4b107'):
        assert by_id[rid]['evidence_tier'] == TIER_2
    assert audit['excluded_count'] == 0


def test_historical_comparison_is_adapted_in_memory_with_audit_version():
    old = {'recommendations': [_row(evidence_tier='tier_1_historically_supported')]}
    original = deepcopy(old)
    adapted, audit = adapt_comparison(old)
    assert old == original
    assert adapted['recommendation_classification_version'] == 2
    assert adapted['recommendations'][0]['evidence_tier'] == TIER_2
    assert adapted['recommendations'][0]['legacy_evidence_tier'] == 'tier_1_historically_supported'
    assert audit['classification_version'] == 2
