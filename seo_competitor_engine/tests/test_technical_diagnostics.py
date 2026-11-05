import sys
import types
import unittest

# The existing project supplies scripts.resolve_pages; stub only when run in isolated patch.
if 'scripts.resolve_pages' not in sys.modules:
    scripts = types.ModuleType('scripts')
    scripts.__path__ = []
    resolve = types.ModuleType('scripts.resolve_pages')
    resolve.normalized_url = lambda u: (u or '').rstrip('/').lower()
    sys.modules['scripts'] = scripts
    sys.modules['scripts.resolve_pages'] = resolve

from normalization.lighthouse import normalize_lighthouse
from analysis.technical_diagnostics import compare_technical, sanitize_url

URL = 'https://example.com/aviator'

def raw(url=URL):
    return {
        'requestedUrl': url, 'finalDisplayedUrl': url, 'lighthouseVersion': '13.5.0',
        'categories': {'performance': {'score': .28}},
        'audits': {
            'largest-contentful-paint': {'numericValue': 24900},
            'bootup-time': {'numericValue': 6000, 'scoreDisplayMode': 'metricSavings',
                            'details': {'items': [{'url': 'https://a.test/script.js?secret=abc#x',
                                                   'total': 1600, 'scripting': 1200, 'node': '<private>'}]}},
            'unused-javascript': {'scoreDisplayMode': 'metricSavings', 'displayValue': 'Est savings of 1,108 KiB',
                                  'details': {'items': [{'url': 'https://a.test/main.js?k=1', 'wastedBytes': 300000}]}},
            'lcp-discovery-insight': {'scoreDisplayMode': 'notApplicable'},
            'image-delivery-insight': {'details': {'items': []}, 'scoreDisplayMode': 'metricSavings'},
        },
    }

class TechnicalDiagnosticsTests(unittest.TestCase):
    def norm(self, value=None):
        return normalize_lighthouse(value or raw(), keyword='aviator', side='ours', device='mobile', ranking_url=URL)

    def test_existing_scores_and_metrics_unchanged(self):
        data = self.norm()
        self.assertEqual(data['scores']['performance'], 28)
        self.assertEqual(data['lab_metrics']['largest_contentful_paint_ms'], 24900)
        self.assertEqual(data['status'], 'usable')

    def test_versioned_diagnostics_present_and_missing(self):
        d = self.norm()['technical_diagnostics']
        self.assertEqual(d['javascript_execution']['bootup-time']['status'], 'present')
        self.assertEqual(d['render_blocking']['render-blocking-insight']['status'], 'missing')
        self.assertEqual(d['lcp_breakdown']['lcp-discovery-insight']['status'], 'not_applicable')
        self.assertEqual(d['image_delivery']['image-delivery-insight']['item_count'], 0)

    def test_sensitive_details_not_exported(self):
        d = self.norm()['technical_diagnostics']
        item = d['javascript_execution']['bootup-time']['items'][0]
        self.assertEqual(item['url'], 'https://a.test/script.js')
        self.assertNotIn('node', item)
        self.assertIsNone(sanitize_url('javascript:alert(1)'))

    def test_bad_url_withholds_details(self):
        d = self.norm(raw('https://different.example/aviator'))
        self.assertEqual(d['status'], 'unusable')
        self.assertEqual(d['technical_diagnostics'], {})

    def test_verified_comparison(self):
        a, b = self.norm(), self.norm()
        b['technical_diagnostics']['javascript_execution']['bootup-time']['numeric_value'] = 8500
        result = compare_technical(a, b)
        self.assertEqual(result['status'], 'usable')
        self.assertTrue(any(x['audit_id'] == 'bootup-time' for x in result['observations']))
        self.assertTrue(any(x['audit_id'] == 'unused-javascript' for x in result['investigations']))

    def test_unverified_comparison_withheld(self):
        a, b = self.norm(), self.norm()
        b['final_url_verified'] = False
        self.assertEqual(compare_technical(a, b)['status'], 'withheld')

    def test_missing_audits_not_equated_to_zero(self):
        d = self.norm()['technical_diagnostics']
        self.assertIsNone(d['render_blocking']['render-blocking-insight'].get('numeric_value'))
        self.assertEqual(d['render_blocking']['render-blocking-insight']['status'], 'missing')

if __name__ == '__main__':
    unittest.main()
