"""Offline regression tests for the standardized SEO-content length finding."""
from analysis.comparison_engine import build_findings


def _content(ours=795, benchmark=446, comparable=True, method='rendered-main-innertext-v2'):
    return {'seo_content_comparison': {'ours': ours, 'benchmark': benchmark,
                                       'comparable': comparable, 'method': method},
            'word_count': {'ours': 867, 'competitor': 2801}}


def _length(onpage):
    return [f for f in build_findings({}, onpage=onpage) if f['category'] == 'content_length']


def test_uses_verified_standardized_counts_only():
    findings = _length(_content())
    assert len(findings) == 1
    assert 'ours 795 vs benchmark 446' in findings[0]['evidence']
    assert '867' not in findings[0]['evidence']
    assert '2801' not in findings[0]['evidence']
    assert findings[0]['evidence_type'] == 'verified_cleaned_content_metric'


def test_withholds_if_upstream_validation_failed():
    assert _length(_content(comparable=False)) == []


def test_withholds_if_method_mismatch():
    assert _length(_content(method='rendered-main-clean-v1')) == []


def test_withholds_if_count_missing_or_invalid():
    assert _length(_content(ours=None)) == []
    assert _length(_content(benchmark=True)) == []
    assert _length(_content(ours=-1)) == []


def test_never_falls_back_to_legacy_body_counts():
    assert _length({'word_count': {'ours': 867, 'competitor': 2801}}) == []


def test_zero_is_valid_when_verified():
    assert 'ours 0 vs benchmark 446' in _length(_content(ours=0))[0]['evidence']


def test_other_findings_still_work():
    findings = build_findings({'google': {'position_gap': 1, 'benchmark_position': 1,
                                          'our_position': 2}}, onpage=_content())
    assert {f['category'] for f in findings} == {'ranking', 'content_length'}
