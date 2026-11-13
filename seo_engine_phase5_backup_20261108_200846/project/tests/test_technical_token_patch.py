import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'llm_foundation' / 'request_optimizer.py'
spec = importlib.util.spec_from_file_location('technical_optimizer_under_test', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    investigations = []
    for name in ('javascript_execution', 'unused_javascript', 'image_delivery', 'render_blocking'):
        investigations.append({
            'area': name, 'title': 'Review ' + name, 'priority': 'high',
            'measurement': {'value': 160, 'unit': 'ms'},
            'affected_resources': [{'url': 'https://example.org/' + name + '.js', 'wastedMs': 160,
                                    'unneeded': 'x' * 1200}],
            'actions': ['Verbose actions ' * 200], 'note': 'Extra notes ' * 100})
    return {'schema_version': '1.0', 'task': 'technical',
            'investigation': {'keyword': 'aviator'},
            'tracked_website': {'domain': 'ours.example'},
            'competitors': [{'domain': 'benchmark.example'}],
            'evidence_quality': {'lighthouse_ours_mobile': 'usable', 'lighthouse_benchmark_mobile': 'usable'},
            'evidence': {'serp': {'ranking_summary': {'our_position': 2, 'benchmark_position': 1}},
                         'technical': {'mobile_audits': {side: {'scores': {'performance': 28, 'seo': 100},
                             'lab_metrics': {'largest_contentful_paint_ms': 24000,
                                             'total_blocking_time_ms': 2100,
                                             'cumulative_layout_shift': 0}} for side in ('ours', 'benchmark')},
                             'detailed_analysis': {'status': 'usable', 'investigations': investigations,
                                                   'observations': [{'long': 'x' * 3000}]}}}}


def test_preserves_four_investigations_and_critical_metrics():
    original = fixture()
    compact = mod.optimize_packet('technical', original)
    tech = compact['evidence']['technical']
    assert len(tech['detailed_analysis']['investigations']) == 4
    assert tech['mobile_audits']['ours']['lab_metrics']['largest_contentful_paint_ms'] == 24000
    assert tech['detailed_analysis']['investigations'][0]['affected_resources'][0]['url'].startswith('https://')
    assert 'observations' not in tech['detailed_analysis']
    assert original['evidence']['technical']['detailed_analysis']['observations']


def test_prompt_within_budget_and_paths_present():
    compact, system, prompt, estimate = mod.prepare_request('technical', fixture(),
        skills='Use verified evidence only.', instructions='Analyse mobile Lighthouse evidence.')
    assert estimate > 2050  # full evidence now retained; server limit is configurable
    assert 'evidence.technical' in prompt
    assert compact['evidence']['technical']['detailed_analysis']['status'] == 'usable'


def test_missing_technical_evidence_fails_closed():
    packet = fixture()
    del packet['evidence']['technical']
    try:
        mod.optimize_packet('technical', packet)
    except ValueError as exc:
        assert 'Missing technical evidence' in str(exc)
    else:
        raise AssertionError('Missing technical evidence must fail')
