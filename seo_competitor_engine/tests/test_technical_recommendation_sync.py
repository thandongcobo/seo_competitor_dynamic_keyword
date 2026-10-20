import unittest
from pathlib import Path
# The full project supplies analysis.advanced_evidence. In isolated patch tests,
# provide only the irrelevant keyword-classifier dependency.
import sys
import types
try:
    from analysis.advanced_evidence import classify_opportunity_relevance
except ModuleNotFoundError:
    stub = types.ModuleType('analysis.advanced_evidence')
    stub.classify_opportunity_relevance = lambda *args: ('excluded', '')
    sys.modules['analysis.advanced_evidence'] = stub
from analysis.recommendations import generate_recommendations


class TechnicalRecommendationSyncTests(unittest.TestCase):
    def generate(self, detail=None):
        kwargs = dict(keyword='aviator', ranking_urls={'ours':'https://ours.example/aviator', 'benchmark':'https://other.example/aviator'},
                      advanced_evidence={'technical':{'mobile':{'lab_metrics':{'largest_contentful_paint_ms':{'ours':24908},'total_blocking_time_ms':{'ours':2122}}}}}, onpage={})
        if detail is not None:
            kwargs['technical_comparison']={'mobile':{'detailed_analysis':detail}}
        return generate_recommendations(**kwargs)

    def tech(self, detail=None):
        return next(x for x in self.generate(detail) if x['id']=='technical-mobile')

    def test_verified_details_change_limitation(self):
        d={'status':'usable','scope':'exact_serp_pages_mobile_lab','investigations':[
            {'area':'javascript_execution','confidence':'investigation_only','title':'JS','supporting_observation':'Measured','actions':['Profile']},
            {'area':'image_delivery','confidence':'investigation_only','title':'Images','supporting_observation':'Measured','actions':['Inspect']} ]}
        x=self.tech(d)
        self.assertIn('JavaScript execution',x['limitations'])
        self.assertIn('image delivery',x['limitations'])
        self.assertIn('precise cause of slow LCP',x['limitations'])
        self.assertNotIn('Only summary lab metrics',x['limitations'])
        self.assertEqual(x['priority'],'high')

    def test_summary_only(self):
        self.assertIn('Only summary lab metrics',self.tech()['limitations'])

    def test_withheld_detail(self):
        d={'status':'withheld','scope':'exact_serp_pages_mobile_lab','investigations':[{'area':'javascript_execution','title':'JS','confidence':'investigation_only','supporting_observation':'x','actions':['x']}]}
        self.assertIn('Only summary lab metrics',self.tech(d)['limitations'])

    def test_unverified_scope(self):
        d={'status':'usable','scope':'domain','investigations':[{'area':'javascript_execution','title':'JS','confidence':'investigation_only','supporting_observation':'x','actions':['x']}]}
        self.assertIn('Only summary lab metrics',self.tech(d)['limitations'])

    def test_other_recommendations_unchanged(self):
        d={'status':'usable','scope':'exact_serp_pages_mobile_lab','investigations':[{'area':'javascript_execution','title':'JS','confidence':'investigation_only','supporting_observation':'x','actions':['x']}]}
        a=self.generate(); b=self.generate(d)
        self.assertEqual([(x['id'],x['priority'],x['order']) for x in a],[(x['id'],x['priority'],x['order']) for x in b])

    def test_pipeline_wires_comparison(self):
        src=(Path(__file__).resolve().parents[1]/'scripts'/'run_analysis.py').read_text()
        self.assertIn('technical_comparison=technical_comparison',src)
