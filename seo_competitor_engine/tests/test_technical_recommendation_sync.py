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
        return next(x for x in self.generate(detail) if x['id']=='technical-mobile-javascript_execution')

    def test_verified_details_change_limitation(self):
        d={'status':'usable','scope':'exact_serp_pages_mobile_lab','investigations':[
            {'area':'javascript_execution','confidence':'investigation_only','title':'JS','supporting_observation':'Measured','actions':['Profile'],'affected_resources':[{'url':'https://ours.example/app.js','total':1200}]},
            {'area':'image_delivery','confidence':'investigation_only','title':'Images','supporting_observation':'Measured','actions':['Inspect'],'affected_resources':[{'url':'https://ours.example/hero.webp','wastedBytes':5000}]} ]}
        x=self.tech(d)
        self.assertIn('JavaScript execution',x['limitations'])
        image=next(r for r in self.generate(d) if r['id']=='technical-mobile-image_delivery')
        self.assertEqual(image['id'], 'technical-mobile-image_delivery')
        self.assertIn('image delivery',image['limitations'])
        self.assertIn('does not establish ranking causation', x['interpretation'])
        self.assertNotIn('Only summary lab metrics',x['limitations'])
        self.assertEqual(x['priority'],'medium')
        self.assertEqual(len([r for r in self.generate(d) if r['id'].startswith('technical-mobile-')]), 2)

    def test_summary_only_stays_in_audit(self):
        self.assertEqual(self.generate(), [])

    def test_withheld_detail_stays_in_audit(self):
        d={'status':'withheld','scope':'exact_serp_pages_mobile_lab','investigations':[{'area':'javascript_execution','title':'JS','confidence':'investigation_only','supporting_observation':'x','actions':['x']}]}
        self.assertEqual(self.generate(d), [])

    def test_unverified_scope_stays_in_audit(self):
        d={'status':'usable','scope':'domain','investigations':[{'area':'javascript_execution','title':'JS','confidence':'investigation_only','supporting_observation':'x','actions':['x']}]}
        self.assertEqual(self.generate(d), [])

    def test_other_recommendations_unchanged(self):
        d={'status':'usable','scope':'exact_serp_pages_mobile_lab','investigations':[{'area':'javascript_execution','title':'JS','confidence':'investigation_only','supporting_observation':'x','actions':['x'],'affected_resources':[{'url':'https://ours.example/app.js','total':1200}]}]}
        a=self.generate(); b=self.generate(d)
        self.assertEqual(a, [])
        self.assertEqual([x['id'] for x in b], ['technical-mobile-javascript_execution'])
        self.assertEqual(b[0]['evidence_tier'], 'tier_1_strong_evidence')
        self.assertIn('script coverage', ' '.join(b[0]['actions']))

    def test_pipeline_wires_comparison(self):
        src=(Path(__file__).resolve().parents[1]/'scripts'/'run_analysis.py').read_text()
        self.assertIn('technical_comparison=technical_comparison',src)

