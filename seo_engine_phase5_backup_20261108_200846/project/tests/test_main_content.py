from collectors.main_content import JS_EXTRACT, EXTRACTION_VERSION, extract_main_content

class FakePage:
    def __init__(self, result):
        self.result = result
        self.script = None
    def evaluate(self, script):
        self.script = script
        return self.result


def test_version_and_shared_extractor():
    page = FakePage({'seo_content_word_count': 625, 'seo_content_status': 'candidate'})
    assert extract_main_content(page)['seo_content_word_count'] == 625
    assert page.script == JS_EXTRACT
    assert EXTRACTION_VERSION == 'rendered-main-innertext-v2'


def test_uses_live_rendered_innertext_not_text_node_traversal():
    assert 'el.innerText' in JS_EXTRACT
    assert 'createTreeWalker' not in JS_EXTRACT
    assert 'cloneNode' not in JS_EXTRACT
    assert 'nav,footer,header' in JS_EXTRACT


def test_restores_original_styles():
    assert 'finally' in JS_EXTRACT
    assert "node.getAttribute('style')" in JS_EXTRACT
    assert "node.removeAttribute('style')" in JS_EXTRACT
    assert "node.setAttribute('style', style)" in JS_EXTRACT


def test_status_is_candidate_not_semantic_verification():
    assert "'candidate' : 'unverified'" in JS_EXTRACT
    assert 'seo_content_method' in JS_EXTRACT


def test_normalizer_compatibility():
    from normalization.pages import normalize_page
    raw = {'seo_content_word_count': 625, 'seo_content_method': EXTRACTION_VERSION,
           'seo_content_status': 'verified_candidate', 'seo_content_selector': 'main:nth-of-type(1)',
           'rendered_main_word_count': 625, 'main_word_count': 3948,
           'ranking_url': 'https://example.com/aviator'}
    result = normalize_page(raw)
    assert result['seo_content_word_count'] == 625
    assert result['seo_content_method'] == EXTRACTION_VERSION
    assert result['main_word_count'] == 3948
    assert result['evidence_scope'] == 'page'


def test_missing_measurement_is_not_zero():
    from normalization.pages import normalize_page
    result = normalize_page({})
    assert result['seo_content_word_count'] is None
    assert result['seo_content_status'] is None
