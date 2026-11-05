"""Production/debug SERP mode regression tests. No live Google requests."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from collectors import team_serp_adapter as adapter


class Page:
    url = 'https://www.google.com/search?q=aviator&gl=za&hl=en&pws=0'
    def evaluate(self, script):
        return [
            {'index': 1, 'title': 'Betway', 'href': 'https://betway.co.za/aviator', 'ancestor_text': 'betway.co.za'},
            {'index': 2, 'title': 'Hollywoodbets', 'href': 'https://hollywoodbets.net/aviator', 'ancestor_text': 'hollywoodbets.net'},
            {'index': 3, 'title': 'Other', 'href': 'https://other.org/aviator', 'ancestor_text': 'other.org'},
        ]
    def close(self):
        pass


def _collect(tmp_path, enabled):
    page = Page()
    rows = [
        {'title': 'Betway', 'url': 'https://betway.co.za/aviator', 'domain': 'betway.co.za'},
        {'title': 'Hollywoodbets', 'url': 'https://hollywoodbets.net/aviator', 'domain': 'hollywoodbets.net'},
        {'title': 'Other', 'url': 'https://other.org/aviator', 'domain': 'other.org'},
    ]
    team = SimpleNamespace(search_google=lambda keyword: page,
        extract_organic_results=lambda p: rows,
        BROWSER=SimpleNamespace(close=lambda: None))
    config = SimpleNamespace(serp_diagnostics_enabled=enabled,
        our_domain='hollywoodbets.net', serp_depth=3)
    with patch.object(adapter, 'settings', config), \
         patch.object(adapter, 'RAW_DIR', tmp_path / 'raw'), \
         patch.object(adapter, 'load_team_module', return_value=team), \
         patch.object(adapter, 'is_challenge', return_value=False), \
         patch.object(adapter, 'capture_serp_diagnostics', return_value={}) as capture:
        result = adapter.collect_once('aviator', depth=3, max_search_depth=10)
    return result, capture, tmp_path


def test_production_mode_does_not_capture_detailed_diagnostics(tmp_path):
    result, capture, base = _collect(tmp_path, False)
    capture.assert_not_called()
    assert result['validation']['status'] == 'checks_passed'
    assert result['tracked_site']['rank'] == 2
    assert not result['serp_diagnostics_enabled']
    assert 'diagnostics' not in result and 'diagnostics_directory' not in result
    assert not (base / 'diagnostics').exists()
    assert len(list((base / 'raw' / 'serp' / 'pages').rglob('page_*.json'))) == 1


def test_debug_mode_keeps_diagnostic_reports(tmp_path):
    result, capture, base = _collect(tmp_path, True)
    capture.assert_called_once()
    assert result['serp_diagnostics_enabled']
    assert result['diagnostics']['pages_diagnosed'] == 1
    report = base / 'diagnostics' / 'google' / 'aviator' / result['diagnostics']['run_id'] / 'run_report.json'
    assert report.is_file()
    assert json.loads(report.read_text())['tracked_site']['rank'] == 2
    assert [r['url'] for r in result['organic_results']] == [
        'https://betway.co.za/aviator', 'https://hollywoodbets.net/aviator', 'https://other.org/aviator']
