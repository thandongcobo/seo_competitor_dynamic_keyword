import json
import unittest
from types import SimpleNamespace
from llm_foundation.inference import parse_json, run_specialist

class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
    def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(self.responses)))])

class Tests(unittest.TestCase):
    def setUp(self):
        self.evidence = {'evidence': {'onpage': {'title': 'Example'}}}
        self.valid = {'schema_version':'1.0','task':'onpage','status':'usable',
                      'findings':[{'observation':'Title observed','interpretation':'Review targeting',
                                   'evidence_paths':['evidence.onpage.title'],
                                   'counterevidence':'Ranking cause unknown','recommended_action':'Verify title'}],
                      'limitations':['No causality']}
    def test_valid(self):
        output, meta = run_specialist('onpage', self.evidence, client=FakeClient([json.dumps(self.valid)]),
                                      model='test', skills='rules', instructions='task')
        self.assertEqual(meta['attempts'], 1)
        self.assertEqual(output['task'], 'onpage')
    def test_retry_invalid_json(self):
        output, meta = run_specialist('onpage', self.evidence,
                                      client=FakeClient(['not json',json.dumps(self.valid)]),
                                      model='test', skills='rules', instructions='task')
        self.assertEqual(meta['attempts'], 2)
    def test_reject_unknown_path(self):
        invalid = json.loads(json.dumps(self.valid))
        invalid['findings'][0]['evidence_paths']=['evidence.missing']
        with self.assertRaises(RuntimeError):
            run_specialist('onpage',self.evidence,client=FakeClient([json.dumps(invalid)]),
                           model='test',skills='rules',instructions='task',attempts=1)
    def test_reject_wrong_task(self):
        invalid = dict(self.valid, task='backlinks')
        with self.assertRaises(RuntimeError):
            run_specialist('onpage',self.evidence,client=FakeClient([json.dumps(invalid)]),
                           model='test',skills='rules',instructions='task',attempts=1)
    def test_reject_fences(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_json('```json\n{}\n```')

if __name__ == '__main__':
    unittest.main()
