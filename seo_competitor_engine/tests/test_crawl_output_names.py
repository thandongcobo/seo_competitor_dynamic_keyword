from scripts.crawl_pages import crawl_output_filename


def test_priority_names_remain_compatible():
    assert crawl_output_filename('aviator', 'google', 'ours', 'https://example.com/a', True) == 'aviator_google_ours.json'
    assert crawl_output_filename('aviator', 'google', 'benchmark', 'https://example.com/b', True) == 'aviator_google_benchmark.json'


def test_candidate_urls_same_domain_are_distinct_and_stable():
    a = crawl_output_filename('aviator', 'google', 'betway.co.za', 'https://betway.co.za/aviator', False)
    b = crawl_output_filename('aviator', 'google', 'betway.co.za', 'https://betway.co.za/other', False)
    assert a != b
    assert a == crawl_output_filename('aviator', 'google', 'betway.co.za', 'https://betway.co.za/aviator', False)


def test_unsafe_labels_are_sanitized():
    name = crawl_output_filename('online_slots', 'google', 'a:b/c\\d', 'https://example.com/', False)
    assert ':' not in name and '/' not in name and '\\' not in name
