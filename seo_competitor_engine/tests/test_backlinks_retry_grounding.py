"""Offline regression tests for focused backlink numeric/citation retries."""
import json
from pathlib import Path
from types import SimpleNamespace

from llm_foundation.focused_recommendations import task_packet, task_request, validate_task
from scripts import run_llm_focused_recommendations as runner


def packet():
    return {
        'schema_version': '1.0', 'keyword': 'sample query', 'market': 'Example market',
        'search_engine': 'google',
        'tracked': {'domain': 'one.example', 'url': 'https://one.example/page', 'position': 2},
        'benchmark': {'domain': 'two.example', 'url': 'https://two.example/page', 'position': 1},
        'limitations': ['Single historical SERP observation.'],
        'facts': [
            {'id': 'SERP', 'statement': 'Observed ranking only', 'values': {'ours': 2, 'benchmark': 1}},
            {'id': 'BL_PAGE', 'statement': 'Exact-page backlink counts', 'values': {'ours': {'backlinks': 120}, 'benchmark': {'backlinks': 140}}},
            {'id': 'BL_DOMAIN', 'statement': 'Domain-wide backlink counts', 'values': {'ours': {'backlinks': 1000}, 'benchmark': {'backlinks': 800}}},
        ],
        'specialist_findings': [
            {'id': 'BACKLINKS_01', 'task': 'backlinks', 'finding': {'observation': 'Page counts differ.', 'evidence_paths': ['evidence.backlinks.page.ours']}},
            {'id': 'BACKLINKS_02', 'task': 'backlinks', 'finding': {'observation': 'Domain counts differ.', 'evidence_paths': ['evidence.backlinks.domain.ours']}},
        ],
        'specialist_fact_links': {'BACKLINKS_01': ['BL_PAGE', 'SERP'], 'BACKLINKS_02': ['BL_DOMAIN', 'SERP']},
    }


def result():
    def plan(title, fid, eid):
        return {
            'title': title, 'rationale': 'Review the observed evidence before taking action.',
            'owner': 'SEO team', 'priority': 'medium',
            'implementation_steps': ['Inspect the relevant saved backlink sources.', 'Verify relevant opportunities before outreach.'],
            'success_measure': 'Document verified source data and review any resulting changes.',
            'uncertainty': 'No causal ranking effect is established.',
            'evidence_ids': [eid], 'specialist_finding_ids': [fid],
            'simple_explanation': 'The observed backlink counts differ.',
            'technical_explanation': 'Validate the source and scope of the backlink counts.',
        }
    def disposition(fid, i, eid):
        return {
            'specialist_finding_id': fid, 'outcome': 'action', 'plan_indices': [i],
            'simple_explanation': 'The measured counts differ.',
            'technical_explanation': 'Verify backlink source and measurement scope.',
            'next_step': 'Review the evidence and record relevant sources.',
            'reason': 'The counts are descriptive rather than causal.', 'evidence_ids': [eid],
        }
    return {'schema_version': '1.0', 'task': 'backlinks',
            'implementation_plans': [plan('Page backlink audit', 'BACKLINKS_01', 'BL_PAGE'),
                                     plan('Domain backlink audit', 'BACKLINKS_02', 'BL_DOMAIN')],
            'finding_dispositions': [disposition('BACKLINKS_01', 0, 'BL_PAGE'),
                                     disposition('BACKLINKS_02', 1, 'BL_DOMAIN')]}


def test_backlink_prompt_is_generic_and_fact_scoped():
    scoped = task_packet(packet(), 'backlinks')
    assert {x['id'] for x in scoped['facts']} == {'SERP', 'BL_PAGE', 'BL_DOMAIN'}
    system, body = task_request(scoped, 'backlinks')
    assert 'Do not invent targets for new links' in system
    assert 'cite BOTH relevant specialist findings' in system
    assert 'BL_DOMAIN alone' in system
    assert 'aviator' not in system.lower()
    assert 'hollywoodbets' not in system.lower()
    assert 'sample query' in body


def test_validator_still_rejects_unsupported_numeric_and_cross_scope_evidence():
    scoped = task_packet(packet(), 'backlinks')
    value = result()
    assert validate_task(value, scoped, 'backlinks') == []
    value['implementation_plans'][1]['evidence_ids'] = ['BL_PAGE', 'BL_DOMAIN']
    value['implementation_plans'][0]['success_measure'] = 'Acquire 90 new backlinks in 10 days.'
    errors = validate_task(value, scoped, 'backlinks')
    assert any('fact not linked' in e for e in errors)
    assert any('numeric claim 90' in e for e in errors)
    assert any('numeric claim 10' in e for e in errors)


def test_retry_guidance_addresses_both_error_types_and_shows_fields():
    value = result()
    value['implementation_plans'][1]['evidence_ids'] = ['BL_PAGE', 'BL_DOMAIN']
    value['implementation_plans'][0]['success_measure'] = 'Acquire 10 links in 90 days.'
    errors = validate_task(value, task_packet(packet(), 'backlinks'), 'backlinks')
    guidance = runner._retry_guidance(errors, value)
    assert 'Acquire 10 links in 90 days' in guidance
    assert 'EVIDENCE LINKAGE CORRECTION' in guidance
    assert 'NUMERIC EVIDENCE CORRECTION' in guidance
    assert 'Do not simply' in guidance
    assert 'ALL flagged fields' in guidance
    assert 'BL_PAGE' in guidance and 'BL_DOMAIN' in guidance


def test_second_attempt_can_correct_both_errors_without_bypassing_validator(tmp_path, monkeypatch):
    scoped = task_packet(packet(), 'backlinks')
    invalid = result()
    invalid['implementation_plans'][1]['evidence_ids'] = ['BL_PAGE', 'BL_DOMAIN']
    invalid['implementation_plans'][0]['success_measure'] = 'Acquire 10 links in 90 days.'
    valid = result()
    sent = []
    responses = iter([invalid, valid])

    class FakeCompletions:
        def create(self, **kwargs):
            sent.append(kwargs['messages'])
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(next(responses))), finish_reason='stop')])

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    parsed, count = runner.generate_task(client, 'test-model', 'backlinks', scoped, 2, 120, 3072, tmp_path)
    assert count == 2
    assert parsed == valid
    assert 'EVIDENCE LINKAGE CORRECTION' in sent[1][-1]['content']
    assert 'NUMERIC EVIDENCE CORRECTION' in sent[1][-1]['content']
    assert (tmp_path / 'backlinks_attempt_1.json').exists()
    assert (tmp_path / 'backlinks_attempt_2.json').exists()


def test_unrelated_errors_do_not_trigger_numeric_or_linkage_advice():
    assert runner._retry_guidance(['Unknown schema version'], {}) == ''
