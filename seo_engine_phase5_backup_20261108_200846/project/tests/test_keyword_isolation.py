from config.settings import keyword_slug

def test_keyword_slug():
    assert keyword_slug('aviator') == 'aviator'
    assert keyword_slug('online slots') != keyword_slug('aviator')
    assert '/' not in keyword_slug('../../unsafe')
