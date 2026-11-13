from collectors.team_serp_pagination import merge_unique, next_page_url

class Link:
    def __init__(self, href): self.href=href
    def get_attribute(self, name): return self.href
class Links:
    def __init__(self, values): self.values=values
    def count(self): return len(self.values)
    def nth(self, i): return Link(self.values[i])
class Page:
    def __init__(self): self.url='https://www.google.com/search?q=aviator'
    def locator(self, selector): return Links(['/search?q=aviator&start=10'] if selector=='a#pnnext' else [])
    def evaluate(self, script, href): return 'https://www.google.com'+href

def test_next():
    next_url, reason = next_page_url(Page(), set())
    assert 'start=10' in next_url and reason == 'valid'
    next_url, reason = next_page_url(Page(), {'https://www.google.com/search?q=aviator&start=10'})
    assert next_url is None and reason != 'valid'

def test_dedupe():
    result, duplicates=merge_unique(
        [{'url':'https://example.org/a','rank':1}],
        [{'url':'https://example.org/a'}, {'url':'https://example.org/b'}, {'url':'https://example.org/c'}], 2)
    assert len(result)==2 and result[-1]['rank']==2 and duplicates==1
