"""Offline, keyword-independent quality audit regression tests."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from llm_foundation.recommendation_quality import audit_recommendations

FIXTURE = Path(__file__).parent / 'fixtures' / 'recommendation_quality_saved_output.json'


def load():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def test_real_saved_response_is_flagged_without_mutation():
    value = load()
    before = copy.deepcopy(value)
    audit = audit_recommendations(value, expected_findings=[x['id'] for x in value['specialist_findings']])
    assert audit['blocking_count'] >= 3
    assert audit['plans_audited'] == 7
    assert audit['dispositions_audited'] == 11
    assert value == before
    codes = {x['code'] for x in audit['issues']}
    assert {'internal_link_direction', 'unproven_necessity', 'unsupported_quality_inference'} <= codes


def test_generic_keyword_and_domains_not_hardcoded():
    value = load()
    text = json.dumps(value).replace('aviator', 'samplewidget').replace('hollywoodbets.net', 'example-a.test').replace('betway.co.za', 'example-b.test')
    generic = json.loads(text)
    audit = audit_recommendations(generic)
    assert audit['blocking_count'] >= 3


def test_neutral_qualified_plan_not_blocked():
    value = {'implementation_plans': [{'title': 'Revise the tracked page title to match its verified purpose',
      'rationale': 'A descriptive difference warrants checking, not proof of ranking causation.',
      'simple_explanation': 'Our title differs from the comparison page; we should verify whether it matches user intent before changing it.',
      'technical_explanation': 'Verify the exact HTML title and canonical URL, assess the query intent, obtain content approval, and monitor controlled changes to search appearance after deployment.',
      'implementation_steps': ['Verify current rendered metadata and page URL.', 'If the intent matches, update the title to accurately describe this page.', 'Recrawl the page and compare measured search appearance.'],
      'uncertainty': 'Any ranking effect is unknown.', 'evidence_ids': ['ON_TITLE']}],
      'finding_dispositions': [{'specialist_finding_id': 'A1', 'simple_explanation': 'Title differs.', 'technical_explanation': 'Inspect current metadata.', 'reason': 'Descriptive difference.'}],
      'verified_factual_findings': [{'statement': 'Title differs.'}]}
    audit = audit_recommendations(value, expected_findings=['A1'])
    assert audit['blocking_count'] == 0


def test_investigation_only_and_arbitrary_target_are_blocked():
    value = {'implementation_plans': [{'title': 'Investigate page optimization',
      'rationale': 'The competitor has a difference.',
      'simple_explanation': 'We should review the page to understand the difference before making any changes.',
      'technical_explanation': 'Analyze the page carefully and document possible improvements for the search engine.',
      'implementation_steps': ['Increase links by 20 to match the competitor.', 'Review the observations.', 'Monitor the rankings.'],
      'success_measure': 'Increase the number of relevant links by 20 to match the competitor.',
      'uncertainty': 'Ranking effect unknown.', 'evidence_ids': ['ON_LINKS']}],
      'finding_dispositions': [], 'verified_factual_findings': [{'statement':'Observed page difference'}]}
    issues = audit_recommendations(value, require_actionable=True)['issues']
    codes = {item['code'] for item in issues}
    assert {'generic_non_actionable_plan', 'arbitrary_implementation_target'} <= codes


def test_causal_claim_and_unresolved_reason_are_checked():
    plan = {'title': 'Rewrite page title', 'rationale': 'The title gap causes lower rankings.',
      'simple_explanation': 'Update the title to better describe this page.',
      'technical_explanation': 'A title update is a testable hypothesis; ranking impact is unknown.',
      'implementation_steps': ['Update the title.', 'Publish the change.', 'Verify the rendered title after deployment.'],
      'success_measure': 'The rendered title accurately represents the page and the same query is monitored over time.',
      'uncertainty': 'No causal effect is established.', 'evidence_ids':['ON_TITLE']}
    value = {'implementation_plans':[plan], 'finding_dispositions':[
      {'specialist_finding_id':'F1','outcome':'investigate','reason':'',
       'simple_explanation':'No action yet.','technical_explanation':'Evidence missing.'}],
      'verified_factual_findings':[{'statement':'Title differs.'}]}
    issues = audit_recommendations(value, expected_findings=['F1'], require_actionable=True)['issues']
    codes = {item['code'] for item in issues}
    assert 'unsupported_causal_ranking_claim' in codes
    assert 'undocumented_unresolved_finding' in codes


def test_missing_findings_are_blocking():
    value = {'implementation_plans': [], 'finding_dispositions': [], 'verified_factual_findings': [{'statement':'Evidence exists'}]}
    audit = audit_recommendations(value, expected_findings=['FINDING_X'])
    assert any(x['code'] == 'missing_findings' for x in audit['issues'])


def test_no_empty_executive_findings_is_review_only():
    value = {'implementation_plans': [], 'finding_dispositions': []}
    audit = audit_recommendations(value)
    assert audit['blocking_count'] == 0
    assert any(x['code'] == 'missing_report_findings' for x in audit['issues'])


def test_unsupported_traffic_claim_detected():
    value = {'implementation_plans': [], 'finding_dispositions': [{'specialist_finding_id': 'F', 'simple_explanation': 'We are losing many users to the competitor.', 'technical_explanation': 'Ranking gap exists.', 'reason': 'Observed SERP rank.'}], 'verified_factual_findings':[{}]}
    audit = audit_recommendations(value)
    assert any(x['code'] == 'unmeasured_user_loss' for x in audit['issues'])


def test_offline_quality_command_makes_no_model_request(tmp_path):
    from argparse import Namespace
    from scripts.run_llm_focused_recommendations import run
    folder = tmp_path / 'llm_outputs'
    folder.mkdir()
    (folder / 'executive_validated.json').write_text(FIXTURE.read_text(encoding='utf-8'), encoding='utf-8')
    args = Namespace(keyword='aviator', output_dir=tmp_path, tasks=None,
                     quality_check_only=True, quality_mode='audit')
    result = run(args, client=None, model=None)
    assert result['blocking_count'] >= 3
    assert (folder / 'recommendation_quality_report.json').exists()


def test_enforced_offline_quality_rejects_bad_saved_response(tmp_path):
    from argparse import Namespace
    import pytest
    from scripts.run_llm_focused_recommendations import run
    folder = tmp_path / 'llm_outputs'
    folder.mkdir()
    (folder / 'executive_validated.json').write_text(FIXTURE.read_text(encoding='utf-8'), encoding='utf-8')
    args = Namespace(keyword='aviator', output_dir=tmp_path, tasks=None,
                     quality_check_only=True, quality_mode='enforce')
    with pytest.raises(ValueError, match='blocking issues'):
        run(args, client=None, model=None)
