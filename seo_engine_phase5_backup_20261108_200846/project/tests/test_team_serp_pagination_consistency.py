from collectors.team_serp_pagination import merge_unique, validate_next_url

BASE = 'https://www.google.com/search?q=aviator&hl=en&gl=za&num=20&pws=0'

def test_valid_next_page():
    assert validate_next_url(BASE, BASE, BASE + '&start=10', {BASE}) == (True, 'valid')

def test_changed_keyword_rejected():
    assert validate_next_url(BASE, BASE, BASE.replace('aviator', 'hotel') + '&start=10', {BASE})[0] is False

def test_changed_country_rejected():
    assert validate_next_url(BASE, BASE, BASE.replace('gl=za', 'gl=us') + '&start=10', {BASE})[0] is False

def test_nonadvancing_rejected():
    assert validate_next_url(BASE, BASE, BASE, set())[0] is False

def test_merging_keeps_order_and_deduplicates():
    result, duplicates = merge_unique([{'url': 'https://a', 'rank': 1}], [{'url': 'https://a'}, {'url': 'https://b'}], 50)
    assert duplicates == 1
    assert [r['url'] for r in result] == ['https://a', 'https://b']
    assert result[-1]['rank'] == 2
