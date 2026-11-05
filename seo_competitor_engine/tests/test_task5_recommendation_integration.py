from analysis.recommendations import generate_recommendations, reconcile_recommendations


def test_specialist_enrichment_joins_one_authoritative_action_by_identity():
    base = [{'id': 'title-check', 'title': 'Verify title', 'target_url': 'https://shop.example/topic',
             'evidence_tier': 'tier_3_plausible_opportunity',
             'evidence': 'Captured title differs from the selected page topic.',
             'interpretation': 'A verified title correction can clarify the page topic.',
             'action_justification': 'The change is based on the exact page capture.',
             'validation_status': 'validated_rule_evidence',
             'evidence_provenance': {'source': 'page capture', 'target_url': 'https://shop.example/topic',
                                     'evidence_ids': ['ON_TITLE']},
             'actions': ['Rewrite the captured title using the verified page topic.']}]
    specialist = {'implementation_plans': [{'title': 'Title improvement',
        'target_url': 'https://shop.example/topic', 'evidence_ids': ['ON_TITLE'],
        'specialist_finding_ids': ['F1'], 'implementation_steps': ['Rewrite only if needed.']} ]}
    rows, audit = reconcile_recommendations(base, specialist, {'issues': []})
    assert len(rows) == 1
    assert rows[0]['specialist_provenance'][0]['specialist_finding_ids'] == ['F1']
    assert audit['eligible_specialist_plan_indices'] == [0]


def test_specialist_plan_with_any_quality_issue_is_withheld():
    base = [{'id': 'title-check', 'target_url': 'https://shop.example/topic',
             'evidence_tier': 'tier_3_plausible_opportunity',
             'evidence': 'Captured title differs from the selected page topic.',
             'interpretation': 'A verified title correction can clarify the page topic.',
             'action_justification': 'The change is based on the exact page capture.',
             'validation_status': 'validated_rule_evidence',
             'evidence_provenance': {'source': 'page capture', 'target_url': 'https://shop.example/topic',
                                     'evidence_ids': ['ON_TITLE']},
             'actions': ['Rewrite the captured title using the verified page topic.']}]
    specialist = {'implementation_plans': [{'title': 'Plan', 'target_url': 'https://shop.example/topic',
        'evidence_ids': ['ON_TITLE'], 'implementation_steps': ['Rewrite title.']} ]}
    rows, audit = reconcile_recommendations(base, specialist,
        {'issues': [{'severity': 'review', 'code': 'missing_post_change_verification',
                     'path': 'implementation_plans[0]'}]})
    assert len(rows) == 1 and 'specialist_provenance' not in rows[0]
    assert audit['withheld_specialist_plans'][0]['reason'] == 'quality_findings'


def test_lighthouse_records_have_short_display_action_and_detailed_resource_appendix_data():
    url = 'https://example.org/product'
    rows = generate_recommendations(keyword='solar pump',
        ranking_urls={'ours': url, 'benchmark': 'https://rival.example/pump'},
        advanced_evidence={'technical': {'mobile': {'lab_metrics': {
            'largest_contentful_paint_ms': {'ours': 8000},
            'total_blocking_time_ms': {'ours': 900}}}}},
        onpage={}, technical_comparison={'mobile': {'detailed_analysis': {
            'status': 'usable', 'scope': 'exact_serp_pages_mobile_lab',
            'investigations': [
                {'area': 'javascript_execution', 'confidence': 'investigation_only',
                 'title': 'Long task', 'supporting_observation': 'Long task on product page',
                 'actions': ['Profile script'], 'affected_resources': [
                     {'url': 'https://example.org/assets/app.js', 'total': 1000}]},
                {'area': 'image_delivery', 'confidence': 'investigation_only',
                 'title': 'Oversized image', 'supporting_observation': 'Image bytes can be reduced',
                 'actions': ['Inspect image'], 'affected_resources': [
                     {'url': 'https://example.org/assets/hero.webp', 'wastedBytes': 5000}]},
            ]}}})
    technical = [row for row in rows if row['id'].startswith('technical-mobile-')]
    assert {row['id'] for row in technical} == {
        'technical-mobile-javascript_execution', 'technical-mobile-image_delivery'}
    assert all('https://' not in row['display_action'] for row in technical)
    assert all(row['evidence_provenance']['resource_candidates'] for row in technical)
    from analysis.recommendation_classification import TIER_1
    assert all(row['evidence_tier'] == TIER_1 for row in technical)
