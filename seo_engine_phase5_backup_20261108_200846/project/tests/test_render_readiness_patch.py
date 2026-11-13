"""Offline tests: no browser, network or DataForSEO credentials required."""
from collectors.playwright_collector import (
    parse_page_html, _content_quality, _stable_render, _wait_for_meaningful_render
)

URL = 'https://example.org/aviator'


def parse(html):
    return parse_page_html(html, requested_url=URL, final_url=URL, status_code=200)


def test_navigation_only_shell_is_not_ready():
    html = '<html><body><nav>' + ('Home Casino Sports Login ' * 40) + '</nav></body></html>'
    d = parse(html)
    assert d['word_count'] >= 80
    assert _content_quality(d)[0] is False


def test_main_content_is_ready():
    html = '<html><body><main><h1>Aviator game</h1>' + ('Game instructions and details. ' * 60) + '</main></body></html>'
    d = parse(html)
    assert d['main_word_count'] > 100
    assert _content_quality(d)[0] is False
    d.update(seo_content_status='candidate', seo_content_word_count=d['main_word_count'])
    assert _content_quality(d) == (True, 'standardized_visible_main_candidate')


def test_legacy_heading_without_verified_main_content_is_not_ready():
    html = '<html><body><h1>Game details</h1><p>' + ('Useful content about this game and its features. ' * 15) + '</p></body></html>'
    assert _content_quality(parse(html))[0] is False


def test_stability_rejects_shell_to_main_change():
    a = dict(final_url=URL, rendered_word_count=148, rendered_main_word_count=0,
             rendered_h1_count=0, readiness_text_prefix='Home Casino Login')
    b = dict(final_url=URL, rendered_word_count=655, rendered_main_word_count=625,
             rendered_h1_count=2, readiness_text_prefix='How to play Aviator')
    assert _stable_render(a, b) is False
    assert _stable_render(b, dict(b)) is True


def test_stability_accepts_small_dynamic_count_change():
    a = dict(final_url=URL, rendered_word_count=650, rendered_main_word_count=620,
             rendered_h1_count=2, readiness_text_prefix='Aviator landing page')
    b = dict(a, rendered_word_count=655, rendered_main_word_count=625)
    assert _stable_render(a, b)


def test_readiness_does_not_stop_on_early_nav_shell(monkeypatch):
    import collectors.playwright_collector as c

    clock = [0.0]
    monkeypatch.setattr(c.time, 'monotonic', lambda: clock[0])

    shell = '<html><body><nav>' + ('Home Casino Sports Login ' * 40) + '</nav></body></html>'
    main = '<html><body><main><h1>Aviator game</h1>' + ('Instructions and game details. ' * 155) + '</main></body></html>'

    class Page:
        url = URL
        def content(self):
            return shell if clock[0] < 3 else main
        def title(self):
            return 'Aviator'
        def evaluate(self, script):
            if clock[0] < 3:
                return dict(rendered_word_count=160, rendered_main_word_count=0,
                            rendered_h1_count=0, readiness_text_prefix='Home Casino Sports', body_blocked=False,
                            seo_content_status='unverified', seo_content_word_count=0,
                            seo_content_selector=None, seo_content_text_prefix='')
            return dict(rendered_word_count=655, rendered_main_word_count=625,
                        rendered_h1_count=1, readiness_text_prefix='Aviator game Instructions', body_blocked=False,
                        seo_content_status='candidate', seo_content_word_count=625,
                        seo_content_selector='main:nth-of-type(1)',
                        seo_content_text_prefix='Aviator game Instructions')
        def wait_for_timeout(self, ms):
            clock[0] += ms / 1000

    result, ready, blocked, reason, samples, elapsed = _wait_for_meaningful_render(Page(), URL, 200, 20000)
    assert ready and not blocked
    assert result['rendered_main_word_count'] == 625
    assert elapsed >= 4
    assert samples >= 5
    assert reason == 'standardized_visible_main_candidate_stable'


def test_recrawl_only_selected_resolved_benchmark(monkeypatch, tmp_path):
    import json
    import sys
    import scripts.recrawl_priority_page as recrawl

    resolved = tmp_path / 'data' / 'processed' / 'aviator' / 'resolved_candidates.json'
    resolved.parent.mkdir(parents=True)
    resolved.write_text(json.dumps({
        'keyword': 'aviator',
        'engines': {'google': {'comparison': {
            'our_url': 'https://www.hollywoodbets.net/aviator', 'our_position': 2,
            'benchmark_url': 'https://www.betway.co.za/aviator', 'benchmark_position': 1,
        }}}
    }), encoding='utf-8')
    monkeypatch.setattr(recrawl, 'ROOT', tmp_path)
    calls = []
    monkeypatch.setattr(recrawl, 'crawl_page', lambda url: calls.append(url) or {
        'requested_url': url, 'final_url': url,
        'word_count': 655, 'rendered_main_word_count': 625,
        'h1_count': 2, 'extraction_status': 'complete',
        'content_quality_reason': 'substantial_main_content_stable',
    })
    monkeypatch.setattr(sys, 'argv', [
        'recrawl_priority_page', '--keyword', 'aviator', '--engine', 'google',
        '--side', 'benchmark',
    ])
    recrawl.main()
    assert calls == ['https://www.betway.co.za/aviator']
    output = tmp_path / 'data' / 'raw' / 'pages' / 'aviator_google_benchmark.json'
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['ranking_position'] == 1
    assert result['target_side'] == 'benchmark'
    assert result['url_alignment'] == 'matched'
    assert not (output.parent / 'aviator_google_ours.json').exists()
