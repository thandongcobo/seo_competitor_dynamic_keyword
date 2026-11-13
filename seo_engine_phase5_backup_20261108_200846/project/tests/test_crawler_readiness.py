from collectors.playwright_collector import parse_page_html, _content_quality


def test_shell_is_incomplete():
    d = parse_page_html('<html><head><title>Betway</title></head><body>Betway</body></html>', requested_url='https://example.org', final_url='https://example.org', status_code=200)
    assert _content_quality(d)[0] is False


def test_meaningful_page_is_complete():
    html = '<html><body><h1>Game details</h1><p>' + ('Useful content about this game and its features. ' * 15) + '</p></body></html>'
    d = parse_page_html(html, requested_url='https://example.org', final_url='https://example.org', status_code=200)
    # Static parsing alone does not establish the live, visible-main candidate
    # required by the current collector contract.
    d.update(seo_content_status='candidate', seo_content_word_count=100)
    assert _content_quality(d) == (True, 'standardized_visible_main_candidate')
