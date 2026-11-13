import pytest
from scripts.diagnose_page_rendering import public_url, target_from_resolved, summary_text


def test_public_url_redacts_query_and_fragment():
    assert public_url('https://user:pass@example.com/path?token=secret#hash') == 'https://example.com/path'


def test_target_from_resolved():
    data = {'engines': {'google': {'comparison': {
        'our_url': 'https://ours.example/a', 'benchmark_url': 'https://other.example/b'}}}}
    assert target_from_resolved(data, 'google', 'benchmark') == 'https://other.example/b'
    assert target_from_resolved(data, 'google', 'ours') == 'https://ours.example/a'


def test_missing_target_is_error():
    with pytest.raises(ValueError):
        target_from_resolved({'engines': {}}, 'google', 'benchmark')


def test_summary_renders_timeline():
    report = {'keyword':'aviator','engine':'google','side':'benchmark',
        'requested_url':'https://betway.co.za/aviator','final_url':'https://betway.co.za/aviator',
        'snapshots':[{'elapsed_seconds':0,'main_document':{'words':148,'main_words':None,'h1':0,'links':27},'frames':[], 'blocked_marker_detected':False}],
        'frames_final':[], 'request_types':{}, 'failed_request_reasons':{}, 'http_error_counts':{}}
    assert 'words=148' in summary_text(report)
