"""Regression tests for complete, scoped repairs of all flagged fields."""
import copy
import json
from types import SimpleNamespace

import pytest

from llm_foundation import quality_repair as repair
from llm_foundation.recommendation_quality import audit_recommendations, internal_link_direction_matches


def sample():
    return {
        'implementation_plans': [
            {'title': 'Unrelated title review', 'rationale': 'Review page metadata.',
             'implementation_steps': ['Review the title.', 'Check intent.', 'Verify deployment.'],
             'success_measure': 'Title is verified.', 'uncertainty': 'Ranking impact is unknown.',
             'simple_explanation': 'Make the page title clearer for visitors.',
             'technical_explanation': 'Check rendered HTML title and search intent before deploying an approved change.',
             'evidence_ids': ['ON_TITLE'], 'specialist_finding_ids': ['OTHER_01']},
            {'title': 'Internal links', 'rationale': 'Captured page contains outgoing links.',
             'implementation_steps': [
                 'Review the outgoing links present on the selected page.',
                 'Identify high-authority pages within sample.example that could link to the selected landing page.',
                 'Verify existing links are useful and crawlable.'
             ],
             'success_measure': 'Increase internal link count and improve crawl depth/link equity flow.',
             'uncertainty': 'No ranking effect is established.',
             'simple_explanation': 'Check whether links on the page are useful to visitors.',
             'technical_explanation': 'Review the outgoing internal-link destinations, anchors and placement separately from inbound measurements.',
             'evidence_ids': ['ON_LINKS'], 'specialist_finding_ids': ['LINK_01']}
        ],
        'finding_dispositions': [
            {'specialist_finding_id': 'OTHER_01', 'outcome': 'action', 'plan_indices': [0],
             'simple_explanation': 'Title needs checking.', 'technical_explanation': 'Verify metadata.',
             'reason': 'Observed title difference.', 'next_step': 'Check title.'},
            {'specialist_finding_id': 'LINK_01', 'outcome': 'action', 'plan_indices': [1],
             'simple_explanation': 'Page link counts differ.', 'technical_explanation': 'Outgoing counts only.',
             'reason': 'Observed count difference.', 'next_step': 'Check outgoing links.'}
        ],
        'verified_factual_findings': [{'statement': 'Observed outgoing link count difference.'}],
    }


def good_patch(data):
    plan = data['implementation_plans'][1]
    steps = list(plan['implementation_steps'])
    steps[1] = ('Independently crawl the website to measure incoming links to the selected ranking URL. '
                'This separate audit is not inferred from the outgoing links counted on that page.')
    return {'fields': {
        'implementation_steps': steps,
        'success_measure': ('Verify outgoing links are relevant, functional and crawlable. '
                            'If a separate incoming-link crawl is completed, report its results independently.')
    }}


class FakeClient:
    def __init__(self, patches):
        self.calls = []
        self.patches = iter(patches)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason='stop', message=SimpleNamespace(content=json.dumps(next(self.patches)))
        )])


def packet():
    return {'keyword': 'different-keyword', 'tracked': 'sample.example', 'benchmark': 'other.example',
            'facts': [], 'specialist_findings': [{'id': 'LINK_01'}, {'id': 'OTHER_01'}]}


def test_required_fields_are_extracted_from_validator_and_prompt():
    data = sample()
    issues = [i for i in audit_recommendations(data)['issues'] if i['code'] == 'internal_link_direction']
    assert len(issues) == 1
    row = data['implementation_plans'][1]
    assert repair._required_field_targets(row, issues) == ['implementation_steps[1]', 'success_measure']
    _, body = repair.repair_request(data, packet(), 'implementation_plans[1]', issues)
    context = json.loads(body)
    assert context['required_patch_fields'] == ['implementation_steps', 'success_measure']
    assert context['required_field_targets'] == ['implementation_steps[1]', 'success_measure']


def test_partial_first_attempt_rejected_then_complete_patch_accepted(monkeypatch):
    data = sample()
    before = copy.deepcopy(data)
    good = good_patch(data)
    partial = {'fields': {'implementation_steps': good['fields']['implementation_steps']}}
    client = FakeClient([partial, good])
    events = []
    monkeypatch.setattr(repair, 'evidence_errors', lambda result, pkt: [])
    candidate, audit = repair.repair_with_client(data, packet(), client, 'test-model', attempts=2, on_event=events.append)
    assert len(client.calls) == 2
    assert 'missing_patch_fields' in client.calls[1]['messages'][1]['content']
    assert audit['all_blocking_resolved']
    assert audit['after']['blocking_count'] == 0
    assert audit['repairs'][0]['required_field_targets'] == ['implementation_steps[1]', 'success_measure']
    assert candidate['implementation_plans'][0] == before['implementation_plans'][0]
    assert candidate['finding_dispositions'] == before['finding_dispositions']
    assert data == before
    assert any(e['kind'] == 'rejected' for e in events)


def test_patch_must_change_each_flagged_list_item_and_success_measure():
    data = sample()
    before = data['implementation_plans'][1]
    proposed = copy.deepcopy(before)
    patch = {'fields': {'implementation_steps': list(before['implementation_steps']),
                        'success_measure': 'Check relevant outgoing links after deployment.'}}
    proposed.update(patch['fields'])
    with pytest.raises(ValueError, match='unchanged_flagged_targets'):
        repair._verify_required_changes(before, patch, proposed,
                                        ['implementation_steps[1]', 'success_measure'])


def test_unresolved_partial_patches_do_not_change_original(monkeypatch):
    data = sample()
    before = copy.deepcopy(data)
    good = good_patch(data)
    partial = {'fields': {'implementation_steps': good['fields']['implementation_steps']}}
    monkeypatch.setattr(repair, 'evidence_errors', lambda result, pkt: [])
    candidate, audit = repair.repair_with_client(data, packet(), FakeClient([partial, partial]), 'model', attempts=2)
    assert audit['after']['blocking_count'] == 1
    assert audit['repairs'][0]['status'] == 'unresolved'
    assert candidate == before == data


def test_change_both_fields_but_leave_unsupported_claim_is_rejected(monkeypatch):
    data = sample()
    bad = good_patch(data)
    bad['fields']['success_measure'] = 'Guarantee better link equity flow and rankings after adding links.'
    monkeypatch.setattr(repair, 'evidence_errors', lambda result, pkt: [])
    candidate, audit = repair.repair_with_client(data, packet(), FakeClient([bad]), 'model', attempts=1)
    assert audit['after']['blocking_count'] == 1
    assert candidate == data


def test_independent_incoming_link_audit_is_not_inherently_flagged():
    data = sample()
    plan = data['implementation_plans'][1]
    plan.update(good_patch(data)['fields'])
    assert internal_link_direction_matches(plan) == []


def test_no_keyword_or_domain_exceptions_in_repair_logic():
    source = repair.repair_request.__code__.co_consts
    assert 'aviator' not in str(source).lower()
    assert 'hollywoodbets' not in str(source).lower()
