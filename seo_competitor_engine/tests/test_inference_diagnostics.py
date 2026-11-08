"""Regression tests for failure-only diagnostics with the optimized request path."""
import json
from types import SimpleNamespace

from llm_foundation import inference as mod


def evidence_fixture():
    """Small but valid input; these tests concern inference, not SEO completeness."""
    return {
        'schema_version': '1.0', 'task': 'onpage',
        'investigation': {'keyword': 'aviator'},
        'tracked_website': {'domain': 'example.org', 'ranking_url': 'https://example.org/aviator'},
        'competitors': [{'domain': 'competitor.example', 'ranking_url': 'https://competitor.example/aviator'}],
        'evidence_quality': {'page_ours': 'usable', 'page_benchmark': 'usable'},
        'evidence': {
            'serp': {'ranking_summary': {'our_position': 2, 'benchmark_position': 1}},
            'onpage': {'pages': {'ours': {'title': 'Aviator'}, 'benchmark': {'title': 'Play Aviator'}},
                       'comparison': {'title_keyword_match': {'ours': True, 'competitor': True}},
                       'comparable': True},
        },
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        content, finish_reason = next(self.responses)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)],
            usage=SimpleNamespace(prompt_tokens=40, completion_tokens=20, total_tokens=60),
        )


def test_failed_json_is_saved(tmp_path):
    client = FakeClient([('```json\n{}\n```', 'length'), ('', 'length')])
    try:
        mod.run_specialist('onpage', evidence_fixture(), client=client, model='test',
                           skills='', instructions='', diagnostic_dir=tmp_path)
    except RuntimeError:
        pass
    else:
        assert False, 'Expected failed inference'
    first = json.loads((tmp_path / 'onpage_attempt_1_failure.json').read_text(encoding='utf-8'))
    second = json.loads((tmp_path / 'onpage_attempt_2_failure.json').read_text(encoding='utf-8'))
    assert first['raw_response'].startswith('```')
    assert first['finish_reason'] == 'length'
    assert first['usage']['total_tokens'] == 60
    assert second['response_empty']


def test_success_does_not_write_diagnostics(tmp_path, monkeypatch):
    # Isolate the response-schema concern to this test and restore the shared
    # production validator when the test ends.
    monkeypatch.setattr(mod, 'validate_output', lambda result, evidence: [])
    client = FakeClient([('{"task":"onpage","findings":[]}', 'stop')])
    result, meta = mod.run_specialist('onpage', evidence_fixture(), client=client,
                                      model='test', skills='', instructions='', diagnostic_dir=tmp_path)
    assert result['task'] == 'onpage'
    assert meta['status'] == 'validated'
    assert not list(tmp_path.iterdir())


def test_missing_onpage_evidence_is_rejected():
    from llm_foundation.request_optimizer import optimize_packet
    try:
        optimize_packet('onpage', {})
    except ValueError as exc:
        assert 'Missing onpage evidence' in str(exc)
    else:
        assert False, 'Missing evidence must be rejected'
