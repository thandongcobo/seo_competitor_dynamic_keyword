"""Offline tests for evidence-grounded numeric retry guidance (no LLM requests)."""
import json
from pathlib import Path
from types import SimpleNamespace

from llm_foundation.focused_recommendations import task_request, fingerprint
from scripts import run_llm_focused_recommendations as runner


def test_numeric_guidance_identifies_all_flagged_fields_without_hardcoding():
    response = {
        'implementation_plans': [{'implementation_steps': ['Check pages', 'Add 4-7 new links to useful pages']}],
        'finding_dispositions': [{'next_step': 'Audit and add 4-7 links'}],
    }
    errors = [
        'implementation_plans[0].implementation_steps[1]: numeric claim 4 is not present in this run evidence',
        'implementation_plans[0].implementation_steps[1]: numeric claim 7 is not present in this run evidence',
        'finding_dispositions[0].next_step: numeric claim 4 is not supported by its cited evidence',
    ]
    guidance = runner._retry_guidance(errors, response)
    assert 'Add 4-7 new links' in guidance
    assert 'Audit and add 4-7 links' in guidance
    assert 'ALL flagged fields' in guidance
    assert 'Do not simply' in guidance
    assert runner._retry_guidance(['unknown fact id'], response) == ''


def test_numeric_guidance_is_safe_with_malformed_model_output():
    errors = ['implementation_plans[9].implementation_steps[1]: numeric claim 123 is not present in this run evidence']
    assert 'implementation_plans[9].implementation_steps[1]' in runner._retry_guidance(errors, {})


def test_initial_prompt_prohibits_unjustified_targets():
    scoped = {'keyword': 'example topic', 'tracked': {'url': 'https://example-one.test/page'},
              'benchmark': {'url': 'https://example-two.test/page'}}
    system, body = task_request(scoped, 'onpage')
    assert 'Do not invent specific quantities' in system
    assert 'conditional steps' in system
    assert 'example topic' in body
    assert 'aviator' not in system.lower()
    assert 'hollywoodbets' not in system.lower()
    assert fingerprint(scoped, 'onpage', 'mock-model') == fingerprint(scoped, 'onpage', 'mock-model')


def test_second_attempt_receives_specific_guidance_and_preserves_validation(tmp_path, monkeypatch):
    invalid = {'implementation_plans': [{'implementation_steps': ['Audit', 'Add 4-7 links']}],
               'finding_dispositions': [{'next_step': 'Add 4-7 links'}]}
    valid = {'implementation_plans': [{'implementation_steps': ['Audit', 'Add relevant links after review']}],
             'finding_dispositions': [{'next_step': 'Audit destinations before editing'}]}
    sent = []
    responses = iter([invalid, valid])

    class FakeCompletions:
        def create(self, **kwargs):
            sent.append(kwargs['messages'])
            result = next(responses)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(result)), finish_reason='stop')])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(runner, 'task_request', lambda scoped, task: ('system', 'prompt'))
    monkeypatch.setattr(runner, 'parse_response', json.loads)

    def validator(value, scoped, task):
        if value == invalid:
            return [
                'implementation_plans[0].implementation_steps[1]: numeric claim 4 is not present in this run evidence',
                'finding_dispositions[0].next_step: numeric claim 7 is not supported by its cited evidence',
            ]
        return []

    monkeypatch.setattr(runner, 'validate_task', validator)
    result, attempts = runner.generate_task(fake, 'mock', 'onpage', {}, 2, 10, 512, tmp_path)
    assert attempts == 2 and result == valid
    assert 'Add 4-7 links' in sent[1][-1]['content']
    assert (tmp_path / 'onpage_attempt_1.json').exists()
    assert (tmp_path / 'onpage_attempt_2.json').exists()
    assert sent[1][-1]['role'] == 'user'
