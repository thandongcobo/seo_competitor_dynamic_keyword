import hashlib
import json

from analysis.recommendations import generate_recommendations


def _enrichment(kind, side, url, value, keyword='residential solar inverter'):
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        'evidence_id': f'ENR_{side}_{kind}', 'keyword': keyword,
        'page': {'side': side, 'url': url}, 'scope': 'page',
        'metric_or_observation': kind, 'value': value,
        'provenance': {'source_sha256': digest, 'source_path': 'saved_fixture.json'},
    }


def _copy_fixture(keyword='residential solar inverter', ours='https://sun.example/solar-inverter',
                  benchmark='https://rival.example/solar-inverter'):
    return [
        _enrichment('page_metadata_and_rendering', 'ours', ours, {
            'title': 'Home Energy Products | Sun Example',
            'meta_description': 'Browse home energy products and services from Sun Example.',
            'canonical': ours, 'robots': 'index,follow', 'status_code': 200,
            'extraction_status': 'complete', 'url_alignment': 'matched'}, keyword),
        _enrichment('rendered_heading_inventory', 'ours', ours, [
            {'level': 'h1', 'text': 'Residential Solar Inverter'},
            {'level': 'h2', 'text': 'How to Choose a Residential Solar Inverter'},
            {'level': 'h2', 'text': 'Battery Compatibility'},
            {'level': 'h3', 'text': 'Installation Options'},
        ], keyword),
        _enrichment('keyword_relevant_visible_passages', 'ours', ours, [
            {'text': 'Compare residential solar inverter capacity with the expected household load.'},
            {'text': 'The guide explains battery compatibility and inverter installation options.'},
        ], keyword),
        _enrichment('page_metadata_and_rendering', 'benchmark', benchmark, {
            'title': 'Solar Inverter Guide | Rival',
            'meta_description': 'Read our solar inverter guide.',
            'canonical': benchmark, 'robots': 'index,follow', 'status_code': 200,
            'extraction_status': 'complete', 'url_alignment': 'matched'}, keyword),
    ]


def test_title_and_meta_candidates_are_distinct_from_observed_copy_and_grounded():
    ours, benchmark = 'https://sun.example/solar-inverter', 'https://rival.example/solar-inverter'
    rows = generate_recommendations(keyword='residential solar inverter',
        ranking_urls={'ours': ours, 'benchmark': benchmark}, advanced_evidence={},
        onpage={'title_keyword_match': {'ours': False, 'competitor': True},
                'meta_keyword_match': {'ours': False, 'competitor': True}},
        enriched_page_evidence=_copy_fixture())
    title = next(row for row in rows if row['id'] == 'onpage-title_keyword_match')
    meta = next(row for row in rows if row['id'] == 'onpage-meta_keyword_match')
    for row in (title, meta):
        proposal = row['action_composition']['proposed_copy']
        assert proposal['status'] == 'proposed_not_observed'
        assert proposal['candidate'] != proposal['replaces_observed']
        assert proposal['validation']['grounded'] is True
        assert proposal['source_evidence_ids']
        assert proposal['candidate'] in row['display_action']
        assert 'not observed source text' in row['display_action']
    assert 'how to choose' in title['action_composition']['proposed_copy']['candidate'].casefold()
    assert 'battery compatibility' in meta['action_composition']['proposed_copy']['candidate'].casefold()
    assert 'how to choose a,' not in meta['action_composition']['proposed_copy']['candidate'].casefold()
    assert 'Solar Inverter Guide | Rival' not in title['action_composition']['proposed_copy']['candidate']


def test_no_replacement_copy_when_exact_page_content_evidence_is_missing():
    row = next(row for row in generate_recommendations(keyword='residential solar inverter',
        ranking_urls={'ours': 'https://sun.example/solar-inverter',
                      'benchmark': 'https://rival.example/solar-inverter'},
        advanced_evidence={}, onpage={'title_keyword_match': {'ours': False, 'competitor': True}})
        if row['id'] == 'onpage-title_keyword_match')
    assert row['action_composition']['specific_copy_generated'] is False
    assert row['action_composition']['proposed_copy'] is None
    assert 'Do not draft or publish' in row['display_action']
    assert row['evidence_tier'] == 'tier_2_moderate_evidence'


def test_stale_or_wrong_page_enrichment_cannot_ground_candidate_text():
    rows = _copy_fixture()
    rows[0]['page']['url'] = 'https://sun.example/other-page'
    row = next(row for row in generate_recommendations(keyword='residential solar inverter',
        ranking_urls={'ours': 'https://sun.example/solar-inverter',
                      'benchmark': 'https://rival.example/solar-inverter'},
        advanced_evidence={}, onpage={'title_keyword_match': {'ours': False, 'competitor': True}},
        enriched_page_evidence=rows) if row['id'] == 'onpage-title_keyword_match')
    assert row['action_composition']['specific_copy_generated'] is False


def test_internal_link_actions_name_actual_source_destination_and_direction():
    ours, benchmark = 'https://sun.example/solar-inverter', 'https://rival.example/solar-inverter'
    source_a = 'https://sun.example/solar-inverter-maintenance'
    source_b = 'https://sun.example/solar-inverter-sizing'
    evidence = [
        _enrichment('rendered_heading_inventory', 'ours', ours, [
            {'level': 'h2', 'text': 'Solar Inverter Maintenance'},
            {'level': 'h2', 'text': 'Solar Inverter Sizing'}]),
        _enrichment('outgoing_internal_link_inventory', 'ours', ours, [
            {'source_url': ours, 'destination_url': source_a, 'direction': 'outgoing_from_selected_page'},
            {'source_url': ours, 'destination_url': source_b, 'direction': 'outgoing_from_selected_page'}]),
    ]
    row = next(row for row in generate_recommendations(keyword='solar inverter',
        ranking_urls={'ours': ours, 'benchmark': benchmark}, advanced_evidence={}, onpage={},
        enriched_page_evidence=evidence) if row['id'] == 'internal-resource-cluster')
    pairs = row['proposed_link_pairs']
    assert {(p['source_url'], p['destination_url']) for p in pairs} == {
        (source_a, ours), (source_b, ours)}
    assert all(p['direction'] == 'supporting_page_to_tracked_page' for p in pairs)
    assert all(p['status'] == 'proposed_pair_to_check; return_link_absence_not_observed' for p in pairs)
    assert row['action_composition']['incoming_link_claim'] is False
    assert 'does not establish that any of those pages link back' in row['actions'][0]


def test_overlapping_javascript_diagnostics_are_coalesced_safely():
    ours, benchmark = 'https://shop.example/product', 'https://rival.example/product'
    shared = 'https://shop.example/assets/vendor.js'
    detail = {'status': 'usable', 'scope': 'exact_serp_pages_mobile_lab', 'investigations': [
        {'area': 'javascript_execution', 'confidence': 'investigation_only', 'title': 'JS work',
         'supporting_observation': 'JS execution observed', 'actions': ['Profile JavaScript'],
         'affected_resources': [
             {'url': shared, 'total': 1200},
             {'url': 'https://fraud-vendor.example/guard.js', 'total': 900}]},
        {'area': 'unused_javascript', 'confidence': 'investigation_only', 'title': 'Unused code',
         'supporting_observation': 'Unused bytes observed', 'actions': ['Inspect coverage'],
         'affected_resources': [
             {'url': shared, 'wastedBytes': 50000},
             {'url': 'https://shop.example/assets/page.js', 'wastedBytes': 25000}]},
    ]}
    rows = generate_recommendations(keyword='product guide',
        ranking_urls={'ours': ours, 'benchmark': benchmark}, onpage={},
        advanced_evidence={'technical': {'mobile': {'lab_metrics': {
            'largest_contentful_paint_ms': {'ours': 8000},
            'total_blocking_time_ms': {'ours': 1200}}}}},
        technical_comparison={'mobile': {'detailed_analysis': detail}})
    javascript = [row for row in rows if row['id'].startswith('technical-mobile-')
                  and ('javascript' in row['id'])]
    assert len(javascript) == 1
    row = javascript[0]
    assert len(row['evidence_provenance']['diagnostic_areas']) == 2
    assert row['evidence_provenance']['overlapping_resource_urls'] == [shared]
    assert 'vendor.js' in row['display_action']
    assert 'guard.js' in row['display_action']
    assert 'third-party' in row['display_action']
    assert 'do not edit' in row['actions'][0].lower() or 'do not' in row['actions'][0].lower()
    assert 'https://' not in row['display_action']
    assert row['action_composition']['third_party_resources_require_owner_review'] is True
