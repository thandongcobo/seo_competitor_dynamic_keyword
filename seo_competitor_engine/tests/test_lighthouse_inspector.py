import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'scripts'/'inspect_lighthouse_diagnostics.py'
spec=importlib.util.spec_from_file_location('inspector',path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class Tests(unittest.TestCase):
    def setUp(self):
        self.raw={'lighthouseVersion':'13.5.0','requestedUrl':'https://www.example.com/aviator',
                  'finalUrl':'https://www.example.com/aviator','fetchTime':'2026-10-12T09:00:00Z',
                  'categories':{'performance':{'score':.25}},'audits':{
                      'render-blocking-resources':{'score':0,'details':{'items':[
                          {'url':'https://cdn.example.com/style.css?token=SECRET','wastedMs':450},
                          {'url':'https://cdn.example.com/other.css','wastedMs':30}]}},
                      'largest-contentful-paint':{'numericValue':24900,'numericUnit':'millisecond'}}}
    def test_matches_exact_url(self):
        r=mod.inspect_report(self.raw,'https://www.example.com/aviator')
        self.assertTrue(r['requested_url_matches_serp'])
        self.assertEqual(r['diagnostics']['render-blocking-resources']['item_count'],2)
    def test_rejects_other_serp_url(self):
        with self.assertRaises(ValueError):mod.inspect_report(self.raw,'https://www.example.com/other')
    def test_sanitizes_query_and_caps_examples(self):
        r=mod.inspect_report(self.raw,max_items=1)
        d=r['diagnostics']['render-blocking-resources']
        self.assertEqual(len(d['items']),1)
        self.assertNotIn('token=',str(r))
        self.assertIn('style.css',str(r))
    def test_missing_audit_marked_missing(self):
        r=mod.inspect_report(self.raw)
        self.assertFalse(r['diagnostics']['unused-javascript']['present'])
    def test_invalid_raw_rejected(self):
        with self.assertRaises(ValueError):mod.inspect_report({'audits':{}})

if __name__=='__main__':unittest.main()
