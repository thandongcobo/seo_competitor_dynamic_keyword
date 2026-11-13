import unittest
from llm_foundation.foundation import canonicalize,make_packets,clean_url
from llm_foundation.validate import path_exists,validate_output

class FoundationTests(unittest.TestCase):
    def source(self):
        url1='https://www.hollywoodbets.net/aviator'
        url2='https://www.betway.co.za/aviator'
        def page(url):
            return {'ranking_url':url,'requested_url':url,'final_url':url,'url_alignment':'matched',
                    'extraction_status':'complete','title':'Aviator','seo_content_text':'private raw page text',
                    'seo_content_word_count':400}
        return {'schema_version':'0.5','keyword':'aviator','labs_location':'South Africa',
          'our_domain':'hollywoodbets.net','benchmark_competitor_domain':'betway.co.za',
          'primary_ranking_urls':{'ours':url1,'benchmark':url2},
          'ranking_summary':{'google':{'our_position':2,'benchmark_position':1}},
          'evidence_quality':{'page_ours':'usable','page_benchmark':'usable'},
          'page_level_evidence':{'ours':page(url1),'benchmark':page(url2)},
          'onpage_comparison':{'seo_content_comparison':{'comparable':True,'ours':400,'benchmark':300}},
          'technical_comparison':{'mobile':{'detailed_analysis':{'status':'usable'}}}}
    def test_dynamic_keyword(self):
        s=self.source();s['keyword']='roulette';c=canonicalize(s)
        self.assertEqual(c['investigation']['keyword'],'roulette')
    def test_no_raw_text(self):
        c=canonicalize(self.source());self.assertNotIn('private raw page text',str(c))
    def test_packet_registry(self):
        p=make_packets(canonicalize(self.source()))
        self.assertEqual(set(p),{'onpage','backlinks','technical','competition'})
        self.assertNotIn('technical',p['onpage']['evidence'])
    def test_unverified_page_withheld(self):
        s=self.source();s['page_level_evidence']['benchmark']['final_url']='https://elsewhere.com/'
        c=canonicalize(s)
        self.assertFalse(c['evidence']['onpage']['comparable'])
        self.assertEqual(c['evidence']['onpage']['pages']['benchmark']['status'],'withheld')
    def test_url_scrub(self):
        self.assertEqual(clean_url('https://example.com/path?key=secret#x'),'https://example.com/path')
    def test_path_validation(self):
        self.assertTrue(path_exists({'evidence':{'serp':{}}},'evidence.serp'))
        self.assertFalse(path_exists({'evidence':{}},'evidence.missing'))
    def test_output_rejects_invalid_reference(self):
        result={'schema_version':'1.0','task':'onpage','status':'usable','limitations':[],
                'findings':[{'observation':'x','interpretation':'y','counterevidence':'none',
                             'recommended_action':'review','evidence_paths':['evidence.fake']}]}
        self.assertTrue(validate_output(result,{'evidence':{}}))
if __name__=='__main__':unittest.main()
