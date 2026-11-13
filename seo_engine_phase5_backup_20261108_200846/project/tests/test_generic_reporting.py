"""Offline report compatibility and investigation-isolation tests."""
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from test_final_report import fixture as comparison_fixture

from scripts.generate_executive_pdf import build_appendix, build_management_pdf
from scripts.run_investigation_offline import (
    _comparison_for_investigation,
    _compatible_executive_payload,
)


def _comparison(keyword, primary_url, competitor_url):
    data = deepcopy(comparison_fixture())
    primary_domain = urlsplit(primary_url).hostname
    competitor_domain = urlsplit(competitor_url).hostname
    data.update({
        'keyword': keyword,
        'our_domain': primary_domain,
        'benchmark_competitor_domain': competitor_domain,
        'primary_ranking_urls': {'ours': primary_url, 'benchmark': competitor_url},
        'ranking_summary': {'google': {'our_position': 2, 'benchmark_position': 1,
                                       'our_url': primary_url, 'benchmark_url': competitor_url}},
        'recommendations': [{
            'id': f'synthetic-{keyword.replace(" ", "-")}',
            'title': f'Improve the {keyword} page title',
            'priority': 'high', 'priority_score': 9,
            'target_url': primary_url,
            'evidence': f'The saved fixture shows the {keyword} title is missing its exact topic phrase.',
            'interpretation': 'A clearer title may improve relevance and search-result understanding.',
            'actions': [f'Update the title on {primary_url} to name {keyword} clearly.'],
            'display_action': f'Update the {keyword} title and verify it in the rendered page and search snippet.',
            'action_justification': 'The fixture directly verifies the current title and supports this targeted edit.',
            'evidence_tier': 'tier_1_strong_evidence',
            'validation_status': 'validated_rule_evidence',
            'evidence_provenance': {'source': 'synthetic_reporting_fixture',
                                    'target_url': primary_url,
                                    'evidence_ids': [f'SYN-{keyword.replace(" ", "-")}'],
                                    'measurement_scope': 'exact_page'},
        }],
    })
    data['page_level_evidence'] = {}
    for side, url in (('ours', primary_url), ('benchmark', competitor_url)):
        data['page_level_evidence'][side] = {
            'ranking_url': url, 'requested_url': url, 'final_url': url,
            'url_alignment': 'matched', 'title': f'{keyword.title()} information',
            'meta_description': f'Information about {keyword}.',
            'headings': {'h1': [keyword.title()]}, 'word_count': 220,
            'internal_link_count': 4, 'structured_data_count': 0,
        }
    data['domain_level_evidence'] = {}
    data['advanced_evidence'] = {}
    data['onpage_comparison'] = {}
    data['intent_alignment'] = {}
    data['evidence_quality'] = {}
    data['technical_comparison'] = {}
    data['cross_engine_summary'] = {}
    data['keyword_comparison'] = {}
    data['backlink_comparison'] = {}
    data['potential_competitors'] = []
    data['findings'] = []
    return data


def _metadata(investigation_id, keyword, primary_url, competitor_url, *, ranked=True):
    return {
        'schema_version': '1.0', 'investigation_id': investigation_id,
        'source': ('synthetic_google_serp_fixture' if ranked else 'synthetic_manual_reporting_fixture'),
        'keyword': keyword, 'search_engine': 'Google' if ranked else None,
        'market': 'Synthetic fixture market' if ranked else None,
        'search_timestamp': '2026-10-20T10:00:00+00:00' if ranked else None,
        'search_context': ({'location_note': 'Synthetic fixture market', 'depth_collected': 10}
                           if ranked else {}),
        'serp_snapshot_reference': 'data/raw/serp/synthetic_fixture.json' if ranked else None,
        'serp_sha256': 'a' * 64 if ranked else None,
        'rankings_available': ranked,
        'tracked_page': {'url': primary_url, 'rank': 2 if ranked else None,
                         'redirect_url': None, 'canonical_url': None},
        'competitor_page': {'url': competitor_url, 'rank': 1 if ranked else None,
                            'redirect_url': None, 'canonical_url': None},
        'evidence_collection_timestamps': {'playwright_page:ours': '2026-10-20T10:01:00Z'},
        'evidence_references': [{'kind': 'playwright_page', 'side': 'ours',
                                 'path': 'data/raw/pages/synthetic.json', 'sha256': 'b' * 64}],
    }


def test_generic_synthetic_keyword_and_competitor_reports_are_isolated(tmp_path):
    cases = [
        ('garden irrigation', 'https://hollywoodbets.net/garden-irrigation',
         'https://greenfield.example/irrigation'),
        ('mortgage calculator', 'https://hollywoodbets.net/mortgage-calculator',
         'https://finance.example/tools/mortgage'),
    ]
    for index, (keyword, primary_url, competitor_url) in enumerate(cases, 1):
        data = _comparison(keyword, primary_url, competitor_url)
        metadata = _metadata(f'{index:032x}', keyword, primary_url, competitor_url)
        pdf = tmp_path / f'{index}.pdf'
        build_management_pdf(pdf, data, {}, None, keyword,
                             investigation_metadata=metadata)
        appendix = build_appendix(data, {}, None, 'synthetic_comparison.json',
                                  investigation_metadata=metadata)
        assert pdf.read_bytes().startswith(b'%PDF')
        assert keyword in appendix
        assert 'SYNTHETIC REPORTING FIXTURE - no live or collected evidence.' in appendix
        assert metadata['investigation_id'] in appendix
        assert primary_url in appendix and competitor_url in appendix
        assert 'Tier 1' in appendix or 'tier_1_strong_evidence' in appendix
        assert 'aviator' not in appendix.casefold()
        assert 'betway' not in appendix.casefold()
        assert 'roulette' not in appendix.casefold()
        assert 'gemma' not in appendix.casefold()


def test_manual_report_marks_serp_positions_unavailable(tmp_path):
    keyword = 'community clinic hours'
    primary_url = 'https://hollywoodbets.net/clinic-hours'
    competitor_url = 'https://care.example/clinic-hours'
    data = _comparison(keyword, primary_url, competitor_url)
    metadata = _metadata('f' * 32, keyword, primary_url, competitor_url, ranked=False)
    appendix = build_appendix(data, {}, None, 'manual_comparison.json',
                              investigation_metadata=metadata)
    pdf = tmp_path / 'manual.pdf'
    build_management_pdf(pdf, data, {}, None, keyword,
                         investigation_metadata=metadata)
    assert 'observed position: Not available' in appendix
    assert ' | #2 |' not in appendix and ' | #1 |' not in appendix
    assert pdf.read_bytes().startswith(b'%PDF')


def test_comparison_identity_and_historical_executive_are_bound_to_investigation(tmp_path):
    keyword = 'garden irrigation'
    primary_url = 'https://hollywoodbets.net/garden-irrigation'
    competitor_url = 'https://greenfield.example/irrigation'
    selection = {'investigation_id': '1' * 32, 'keyword': keyword,
                 'ours': {'domain': 'hollywoodbets.net', 'url': primary_url},
                 'benchmark': {'domain': 'greenfield.example', 'url': competitor_url}}
    comparison = _comparison(keyword, primary_url, competitor_url)
    assert _comparison_for_investigation(selection, comparison)['recommendations']
    mismatched = deepcopy(comparison)
    mismatched['keyword'] = 'aviator'
    try:
        _comparison_for_investigation(selection, mismatched)
    except ValueError as exc:
        assert 'keyword' in str(exc)
    else:
        raise AssertionError('Mismatched comparison keyword was accepted.')

    # A shared executive filename and matching keyword are insufficient without
    # per-investigation evidence, prompt/model and payload hash provenance.
    source = tmp_path / 'shared' / 'garden-irrigation'
    (source / 'llm_outputs').mkdir(parents=True)
    (source / 'llm_outputs' / 'executive_validated.json').write_text('{"keyword":"garden irrigation"}', encoding='utf-8')
    assert not _compatible_executive_payload(source, selection, {'entries': []},
                                             _metadata(selection['investigation_id'], keyword,
                                                       primary_url, competitor_url))
