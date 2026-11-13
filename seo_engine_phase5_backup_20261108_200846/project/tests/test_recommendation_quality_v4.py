"""Offline tests for dynamic recommendation quality checks and targeted repairs."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from llm_foundation.recommendation_quality import (
    audit_recommendations, query_scope_ready, missing_post_change_verification,
    missing_technical_safeguards, audience_mismatch, unmeasured_loss_fields,
)
from llm_foundation import quality_repair as repair

ROOT = Path(__file__).parent


def sample_plan():
    return {
        'title': 'Improve the existing instructional page after checking query intent', 'owner': 'Content', 'priority': 'medium',
        'rationale': 'Observed domain-level ranking differences.',
        'simple_explanation': 'We are losing many users who want instructions.',
        'technical_explanation': 'These are domain-level ranking observations; traffic loss is unverified.',
        'uncertainty': 'Actual click loss is unknown.',
        'implementation_steps': [
            'Verify that the target URLs align with intended content structure.',
            'Improve the existing page for the related queries after verifying exact ranking URLs and intent.',
            'Monitor rankings after publishing the guide.'
        ],
        'success_measure': 'Compare positions for the related queries.',
        'evidence_ids': ['KW_QUERY_GAPS'],
        'specialist_finding_ids': ['COMP_01'],
    }


def report(plan):
    return audit_recommendations({
        'implementation_plans': [plan],
        'finding_dispositions': [{'specialist_finding_id': 'COMP_01',
                                  'simple_explanation': 'A ranking gap was observed.'}],
        'verified_factual_findings': [{'statement': 'Evidence exists.'}],
    }, expected_findings=['COMP_01'])


def codes(plan):
    return {issue['code'] for issue in report(plan)['issues']}


def test_saved_real_output_detects_unmeasured_loss_and_domain_scope():
    original = json.loads((ROOT/'fixtures/quality_v4_saved_response.json').read_text(encoding='utf-8'))
    before = copy.deepcopy(original)
    result = audit_recommendations(original)
    assert 'unmeasured_user_loss' in {i['code'] for i in result['issues']}
    assert 'domain_rank_scope' in {i['code'] for i in result['issues']}
    assert len(original['implementation_plans']) == 7
    assert len(original['finding_dispositions']) == 11
    assert original == before


def test_claim_in_plain_explanation_is_blocked_and_field_targeted():
    plan = sample_plan()
    assert 'unmeasured_user_loss' in codes(plan)
    assert unmeasured_loss_fields(plan) == ['simple_explanation']
    issues = report(plan)['issues']
    assert 'simple_explanation' in repair._required_field_targets(plan, issues)


def test_scope_requires_exact_query_ranking_urls_and_intent_before_content():
    plan = sample_plan()
    assert not query_scope_ready(plan)
    plan['implementation_steps'][0] = ('Identify the exact ranking URL for each query, '
                                      'verify its search intent and existing page coverage.')
    assert query_scope_ready(plan)
    assert 'domain_rank_scope' not in codes(plan)
    plan['implementation_steps'] = [plan['implementation_steps'][1], plan['implementation_steps'][0]]
    assert not query_scope_ready(plan)


def test_investigation_only_plan_does_not_require_new_content_check():
    plan = sample_plan()
    plan['implementation_steps'] = ['Inspect the domain-level evidence.',
                                    'Identify existing ranking URLs.', 'Compare intent.']
    assert query_scope_ready(plan)


def test_post_change_verification_follows_last_change():
    plan = sample_plan()
    plan['implementation_steps'] = ['Audit the page.', 'Update the title via CMS.',
                                    'Verify the rendered title after deployment.']
    assert not missing_post_change_verification(plan)
    plan['implementation_steps'][-1] = 'Update the page again.'
    assert missing_post_change_verification(plan)


def test_script_changes_require_safeguards_not_just_speed_check():
    plan = sample_plan()
    plan['title'] = 'JavaScript bundle review'
    plan['implementation_steps'] = ['Profile the scripts.', 'Defer unused JavaScript.',
                                    'Verify performance after deployment.']
    assert missing_technical_safeguards(plan)
    plan['implementation_steps'].append('Run regression checks on fraud controls and core user flows.')
    assert not missing_technical_safeguards(plan)


def test_audience_contradiction_is_flagged_but_conditional_language_passes():
    plan = sample_plan()
    plan['simple_explanation'] = 'This change will improve search rankings.'
    assert audience_mismatch(plan)
    plan['simple_explanation'] = 'This change may improve relevance, but ranking impact is unknown.'
    assert not audience_mismatch(plan)


def test_prompt_targets_both_scope_and_unmeasured_claim_without_hardcoding():
    plan = sample_plan()
    data = {'implementation_plans': [plan], 'finding_dispositions': [],
            'verified_factual_findings': [{'statement': 'Some evidence.'}]}
    issues = report(plan)['issues']
    system, body = repair.repair_request(data, {
        'keyword': 'unrelated topic', 'tracked': {'domain': 'example.org'},
        'benchmark': {'domain': 'competitor.org'}, 'facts': [], 'specialist_findings': []
    }, 'implementation_plans[0]', issues)
    packet = json.loads(body)
    assert set(packet['required_patch_fields']) >= {'simple_explanation', 'implementation_steps'}
    assert 'EACH related query' in body
    assert 'Aviator' not in body and 'hollywoodbets' not in body
    assert 'JSON object' in system


def test_repair_preserves_unaffected_fields_and_rejects_partial_patch(monkeypatch):
    plan = sample_plan()
    data = {'implementation_plans': [plan],
            'finding_dispositions': [{'specialist_finding_id': 'COMP_01'}],
            'verified_factual_findings': [{'statement': 'Some evidence.'}]}
    original = copy.deepcopy(data)
    new_steps = list(plan['implementation_steps'])
    new_steps[0] = 'Identify exact ranking URL for each query and verify search intent before content work.'
    partial = {'fields': {'implementation_steps': new_steps}}
    full = {'fields': {'implementation_steps': new_steps,
                       'technical_explanation': 'Identify the exact ranking URLs for each related query and compare their intent and existing page coverage before proposing any new content. Then verify that the recommended changes align with the selected page purpose and review results against the same sources after release.',
                       'simple_explanation': 'Domain rankings differ for related queries; actual traffic loss is unknown.'}}
    class Client:
        def __init__(self):
            self.responses = iter([partial, full]); self.calls = 0
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason='stop', message=SimpleNamespace(content=json.dumps(next(self.responses))))])
    client = Client()
    monkeypatch.setattr(repair, 'evidence_errors', lambda *_: [])
    # Full candidate still has other review issues, but two targeted issues disappear.
    fixed, audit = repair.repair_with_client(data, {'facts': [], 'specialist_findings': [{'id': 'COMP_01'}]},
                                            client, 'fake', attempts=2, include_review=True)
    assert client.calls == 2
    assert data == original
    assert fixed['finding_dispositions'] == original['finding_dispositions']
    assert fixed['implementation_plans'][0]['evidence_ids'] == plan['evidence_ids']
    assert audit['after']['blocking_count'] == 0
    assert not {'unmeasured_user_loss', 'domain_rank_scope'} & {i['code'] for i in audit['after']['issues']}
