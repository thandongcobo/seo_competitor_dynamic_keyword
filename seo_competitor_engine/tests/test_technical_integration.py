import ast
from pathlib import Path

from analysis.technical_diagnostics import compare_technical


def audit(url, bootup=4000):
    return {
        'status': 'usable', 'target_verified': True, 'final_url_verified': True,
        'scope': 'page', 'device': 'mobile', 'ranking_url': url,
        'technical_diagnostics': {'javascript_execution': {'bootup-time': {
            'status': 'present', 'numeric_value': bootup, 'numeric_unit': 'millisecond',
            'items': [{'url': 'https://example.com/main.js', 'total': bootup}],
            'display_value': '4s'}}},
    }


def test_valid_matching_targets():
    targets = {'ours': 'https://example.com/a', 'benchmark': 'https://other.com/a'}
    result = compare_technical(audit(targets['ours']), audit(targets['benchmark'], 2000), expected_urls=targets)
    assert result['status'] == 'usable'
    assert any(o['audit_id'] == 'bootup-time' for o in result['observations'])
    assert any(i['area'] == 'javascript_execution' for i in result['investigations'])


def test_reject_stale_serp_url():
    targets = {'ours': 'https://example.com/a', 'benchmark': 'https://other.com/a'}
    result = compare_technical(audit('https://example.com/wrong'), audit(targets['benchmark']), expected_urls=targets)
    assert result['status'] == 'withheld' and not result['observations']


def test_reject_missing_diagnostics():
    a = audit('https://example.com/a')
    a.pop('technical_diagnostics')
    result = compare_technical(a, audit('https://other.com/a'))
    assert result['status'] == 'withheld'


def test_reject_unverified():
    a = audit('https://example.com/a')
    a['final_url_verified'] = False
    assert compare_technical(a, audit('https://other.com/a'))['status'] == 'withheld'


def test_pipeline_preserves_existing_summary_and_adds_details():
    source = (Path(__file__).resolve().parents[1] / 'scripts' / 'run_analysis.py').read_text()
    ast.parse(source)
    assert '"detailed_analysis": (compare_technical(' in source
    assert '"scores":' in source and '"lab_metrics":' in source
    assert 'expected_urls=targets' in source
    assert 'generate_recommendations(' in source
