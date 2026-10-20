import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

P = Path(__file__).resolve().parents[1] / 'scripts' / 'diagnose_serp_content.py'
spec = importlib.util.spec_from_file_location('diag', P)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

class TestTargets(unittest.TestCase):
    def test_exact_urls(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'data.json'
            f.write_text(json.dumps({'keyword':'aviator','primary_ranking_urls':{'ours':'https://hollywoodbets.net/aviator','benchmark':'https://betway.co.za/aviator'}}))
            self.assertEqual(diag.load_targets(f,'aviator')['benchmark'],'https://betway.co.za/aviator')
            with self.assertRaises(ValueError): diag.load_targets(f,'roulette')
    def test_missing_urls(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'data.json'
            f.write_text(json.dumps({'keyword':'aviator','primary_ranking_urls':{'ours':'https://hollywoodbets.net/aviator'}}))
            with self.assertRaises(ValueError):diag.load_targets(f,'aviator')
    def test_no_raw_content_in_summary(self):
        result={'requested_url':'https://a.com/x','observations':[{'elapsed_wait_ms':0,'body_words':2,'html_main_max_words':2,'rendered_main_max_words':2,'h1_count':1,'document_ready_state':'complete','blocked':False,'main_candidates_total':0,'main_candidates':[]}]}
        self.assertIn('body_words=2','\n'.join(diag.summarize(result,'ours')))

if __name__=='__main__': unittest.main()
