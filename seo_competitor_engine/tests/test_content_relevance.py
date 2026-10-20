import unittest
from analysis.onpage import compare_pages
from normalization.pages import normalize_page
from collectors.main_content import JS_EXTRACT, EXTRACTION_VERSION

URLS = ('https://example.org/aviator','https://rival.example/aviator')

def page(url, text):
    return {'ranking_url':url,'requested_url':url,'final_url':url,'url_alignment':'matched',
        'seo_content_method':'rendered-main-innertext-v2','seo_content_status':'verified_candidate',
        'seo_content_word_count':len(text.split()),'seo_content_text':text,
        'extraction_status':'complete','crawl_failed':False,'text_sample':'UNRELATED NAVIGATION FOOTER',
        'headings':{'h1':['Aviator']},'title':'Aviator'}

class Tests(unittest.TestCase):
    def test_extractor_exports_same_text_as_count(self):
        self.assertIn('seo_content_text:chosen ? chosen.text : null', JS_EXTRACT)
        self.assertEqual(EXTRACTION_VERSION, 'rendered-main-innertext-v2')
    def test_normalization_preserves_cleaned_text(self):
        self.assertEqual(normalize_page({'seo_content_text':'hello world'})['seo_content_text'],'hello world')
    def test_cleaned_text_only(self):
        a=page(URLS[0],'aviator play rules casino')
        b=page(URLS[1],'aviator play online guide')
        result=compare_pages(a,b,'aviator')
        self.assertEqual(result['content_relevance_status'],'comparable_cleaned_text')
        self.assertGreater(result['content_token_jaccard'],0)
        self.assertNotIn('unrelated',result['top_shared_terms'])
        self.assertEqual(result['transactional_term_hits']['ours'],1)
    def test_missing_text_withholds_not_fallback(self):
        a=page(URLS[0],'aviator play rules casino')
        b=page(URLS[1],'aviator play online guide')
        del b['seo_content_text']
        result=compare_pages(a,b,'aviator')
        self.assertIsNone(result['content_token_jaccard'])
        self.assertIsNone(result['transactional_term_hits']['ours'])
        self.assertEqual(result['top_shared_terms'],[])
    def test_url_mismatch_withholds(self):
        a=page(URLS[0],'aviator play rules casino')
        b=page(URLS[1],'aviator play online guide')
        b['final_url']='https://other.example/aviator'
        self.assertIsNone(compare_pages(a,b,'aviator')['content_token_jaccard'])
    def test_count_mismatch_withholds(self):
        a=page(URLS[0],'aviator play rules casino')
        b=page(URLS[1],'aviator play online guide')
        b['seo_content_word_count']=999
        self.assertIsNone(compare_pages(a,b,'aviator')['content_token_jaccard'])
    def test_method_mismatch_withholds(self):
        a=page(URLS[0],'aviator play rules casino')
        b=page(URLS[1],'aviator play online guide')
        b['seo_content_method']='old'
        self.assertIsNone(compare_pages(a,b,'aviator')['content_token_jaccard'])

if __name__=='__main__':unittest.main()
