"""Offline tests use synthetic inputs, never invented production SERP evidence."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from collectors.serp_diagnostics import search_context, extraction_audit, run_summary
from collectors.team_serp_adapter import capture_serp_diagnostics


def test_matching_search_context_is_not_claimed_as_precise_geolocation():
    result = search_context('https://www.google.com/search?q=aviator&gl=za&hl=en&pws=0',
                            keyword='aviator', gl='za', hl='en')
    assert not result['context_warning']
    assert all(x == 'match' for x in result['url_parameter_checks'].values())
    assert 'does not verify precise' in result['note']


def test_google_context_mismatch_is_flagged_without_changing_rankings():
    result = search_context('https://www.google.com/search?q=aviator&gl=us&hl=en',
                            keyword='aviator', gl='za', hl='en')
    assert result['context_warning']
    assert result['url_parameter_checks']['gl'] == 'mismatch'
    assert result['url_parameter_checks']['pws'] == 'not_in_final_url'


def test_ai_mode_result_is_flagged_but_preserved():
    rows = [{'title': 'AI Mode replied:', 'url': 'https://example.org/page'},
            {'title': 'Normal page', 'url': 'https://other.org'}]
    copy = [dict(r) for r in rows]
    result = extraction_audit(rows, [{'title': 'AI Mode replied:', 'href': 'https://example.org/page'},
                                     {'title': 'Normal page', 'href': 'https://other.org'}])
    assert result['status'] == 'review_required'
    assert result['suspicious_results'][0]['observed_sequence'] == 1
    assert rows == copy


def test_different_serps_are_not_treated_as_context_failures():
    a = extraction_audit([{'title': 'A', 'url': 'https://a.org'}],
                         [{'title': 'A', 'href': 'https://a.org'}])
    b = extraction_audit([{'title': 'B', 'url': 'https://b.org'}],
                         [{'title': 'B', 'href': 'https://b.org'}])
    assert a['status'] == b['status'] == 'evidence_captured_not_manually_verified'
    assert not run_summary([{'diagnostic_flags': []}], run_id='abc', stop_reason='done')['review_required']


class FakePage:
    url = 'https://www.google.com/search?q=aviator&gl=za&hl=en&pws=0'

    def evaluate(self, script):
        if 'querySelectorAll' in script:
            return [{'index': 1, 'title': 'A', 'href': 'https://a.org'}]
        return {'language': 'en-ZA', 'timezone': 'Africa/Johannesburg'}

    def locator(self, selector):
        return SimpleNamespace(count=lambda: 1)

    def screenshot(self, **kwargs):
        Path(kwargs['path']).write_bytes(b'fake-test-only')

    def content(self):
        return '<html>test-only</html>'


def test_each_run_writes_separate_diagnostic_artifacts(tmp_path):
    team = SimpleNamespace(GOOGLE_GL='za', GOOGLE_HL='en', TIMEZONE='Africa/Johannesburg', HEADLESS=False)
    with patch('collectors.team_serp_adapter.RAW_DIR', tmp_path / 'raw'):
        first = capture_serp_diagnostics(FakePage(), 'aviator', label='page_1', run_id='run_one', team=team)
        second = capture_serp_diagnostics(FakePage(), 'aviator', label='page_1', run_id='run_two', team=team)
    assert first['metadata_path'] != second['metadata_path']
    assert Path(first['html_path']).read_text() == '<html>test-only</html>'
    assert Path(first['metadata_path']).is_file()
    assert json.loads(Path(second['metadata_path']).read_text())['context']['configured']['country_gl'] == 'za'


def test_previous_serp_comparison_does_not_require_same_results():
    from collectors.serp_diagnostics import compare_observations
    a = {'datetime': '2026-10-21T08:00:00Z', 'organic_results': [{'url': 'https://a.org'}]}
    b = {'datetime': '2026-10-21T08:01:00Z', 'organic_results': [{'url': 'https://b.org'}]}
    compared = compare_observations(a, b)
    assert compared['shared_exact_urls'] == 0
    assert compared['first_result_changed']
    assert not compared['configured_context_comparable']
    assert 'not evidence of incorrect' in compared['conclusion']


def test_configured_context_changes_reported_independently_of_serp():
    from collectors.serp_diagnostics import compare_observations
    a = {'page_manifest': [{'search_context': {'configured': {'country_gl': 'za'}}}]}
    b = {'page_manifest': [{'search_context': {'configured': {'country_gl': 'us'}}}]}
    compared = compare_observations(a, b)
    assert compared['configured_context_changes']['country_gl'] == {'previous': 'za', 'current': 'us'}


def test_opaque_google_redirect_matches_title_and_visible_domain_without_false_warning():
    rows = [
        {'title': 'Play Aviator', 'url': 'https://www.hollywoodbets.net/aviator'},
        {'title': 'Aviator', 'url': 'https://spribe.co/games/aviator'},
        {'title': 'Aviator', 'url': 'https://www.betway.co.za/lobby/aviator'},
    ]
    headings = [
        {'index': 1, 'title': 'Play Aviator', 'href': 'https://www.google.com/goto?url=CAESopaque1',
         'ancestor_text': 'Play Aviator\nHollywoodbets\nhttps://www.hollywoodbets.net 4a aviator'},
        {'index': 2, 'title': 'Aviator', 'href': 'https://www.google.com/goto?url=CAESopaque2',
         'ancestor_text': 'Aviator\nSPRIBE\nhttps://spribe.co 4a games'},
        {'index': 3, 'title': 'Aviator', 'href': 'https://www.google.com/goto?url=CAESopaque3',
         'ancestor_text': 'Aviator\nBetway\nhttps://www.betway.co.za 4a lobby'},
    ]
    result = extraction_audit(rows, headings)
    assert result['flags'] == []
    assert result['heading_link_mismatches'] == []
    assert result['opaque_redirect_domain_matches'] == 3
    assert all(r['match_method'] == 'opaque_redirect_title_and_displayed_domain'
               for r in result['heading_matches'])
    assert [r['url'] for r in rows] == [
        'https://www.hollywoodbets.net/aviator', 'https://spribe.co/games/aviator',
        'https://www.betway.co.za/lobby/aviator']


def test_decodable_google_redirect_verifies_exact_destination():
    rows = [{'title': 'Aviator', 'url': 'https://www.hollywoodbets.net/aviator'}]
    headings = [{'index': 1, 'title': 'Aviator',
                 'href': 'https://www.google.com/url?q=https%3A%2F%2Fwww.hollywoodbets.net%2Faviator'}]
    result = extraction_audit(rows, headings)
    assert result['flags'] == []
    assert result['heading_matches'][0]['match_method'] == 'direct_or_decoded_url'


def test_different_destination_with_same_title_is_still_flagged():
    rows = [{'title': 'Aviator', 'url': 'https://www.hollywoodbets.net/aviator'}]
    headings = [{'index': 1, 'title': 'Aviator', 'href': 'https://other.example/aviator',
                 'ancestor_text': 'https://www.hollywoodbets.net'}]
    result = extraction_audit(rows, headings)
    assert result['flags'] == ['some_result_urls_not_matched_to_heading_links']


def test_opaque_redirect_wrong_displayed_domain_is_not_accepted():
    rows = [{'title': 'Aviator', 'url': 'https://www.hollywoodbets.net/aviator'}]
    headings = [{'index': 1, 'title': 'Aviator',
                 'href': 'https://www.google.com/goto?url=CAESopaque',
                 'ancestor_text': 'https://www.hollywoodbets.net.evil.example 4a aviator'}]
    result = extraction_audit(rows, headings)
    assert result['flags'] == ['some_result_urls_not_matched_to_heading_links']


def test_duplicate_indistinguishable_opaque_headings_remain_ambiguous():
    rows = [{'title': 'Aviator', 'url': 'https://www.betway.co.za/aviator'}]
    headings = [
        {'index': 1, 'title': 'Aviator', 'href': 'https://www.google.com/goto?url=opaque1',
         'ancestor_text': 'https://www.betway.co.za 4a aviator'},
        {'index': 2, 'title': 'Aviator', 'href': 'https://www.google.com/goto?url=opaque2',
         'ancestor_text': 'https://www.betway.co.za 4a aviator'},
    ]
    result = extraction_audit(rows, headings)
    assert result['flags'] == ['some_result_urls_not_matched_to_heading_links']
    assert result['heading_matches'][0]['match_method'] == 'ambiguous'
